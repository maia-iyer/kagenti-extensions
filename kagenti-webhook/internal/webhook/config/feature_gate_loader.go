package config

import (
	"context"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
	"sigs.k8s.io/yaml"
)

// FeatureGateLoader loads feature gates from file and watches for changes.
type FeatureGateLoader struct {
	configPath string

	mu      sync.RWMutex
	current *FeatureGates

	onChange []func(*FeatureGates)
}

func NewFeatureGateLoader(configPath string) *FeatureGateLoader {
	return &FeatureGateLoader{
		configPath: configPath,
		current:    DefaultFeatureGates(),
	}
}

// Load reads feature gates from file.
func (l *FeatureGateLoader) Load() error {
	log.Info("Loading feature gates", "path", l.configPath)

	gates := DefaultFeatureGates()

	data, err := os.ReadFile(l.configPath)
	if err != nil {
		if os.IsNotExist(err) {
			log.Info("Feature gates file not found, using defaults (all enabled)")
			logFeatureGates(gates, "compiled-defaults")
			return nil
		}
		return err
	}

	if err := yaml.Unmarshal(data, gates); err != nil {
		return err
	}

	l.mu.Lock()
	l.current = gates
	l.mu.Unlock()

	logFeatureGates(gates, "configmap")

	for _, cb := range l.onChange {
		cb(gates)
	}

	return nil
}

// Get returns current feature gates (thread-safe).
func (l *FeatureGateLoader) Get() *FeatureGates {
	l.mu.RLock()
	defer l.mu.RUnlock()
	return l.current.DeepCopy()
}

// Watch starts watching the feature gates file for changes.
func (l *FeatureGateLoader) Watch(ctx context.Context) error {
	dir := filepath.Dir(l.configPath)

	// If the directory doesn't exist yet (e.g. volume not mounted),
	// skip watching — defaults are already loaded.
	if _, err := os.Stat(dir); os.IsNotExist(err) {
		log.Info("Feature gates directory not found, skipping watcher (using defaults)", "dir", dir)
		return nil
	}

	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		return err
	}

	if err := watcher.Add(dir); err != nil {
		watcher.Close()
		return err
	}

	log.Info("Watching feature gates directory for changes", "dir", dir)

	go func() {
		defer watcher.Close()

		var debounceTimer *time.Timer

		for {
			select {
			case <-ctx.Done():
				log.Info("Feature gates watcher stopped")
				return

			case event, ok := <-watcher.Events:
				if !ok {
					return
				}

				if event.Op&(fsnotify.Create|fsnotify.Write|fsnotify.Remove) != 0 {
					log.Info("Feature gates change detected", "event", event.Name, "op", event.Op)

					if debounceTimer != nil {
						debounceTimer.Stop()
					}
					debounceTimer = time.AfterFunc(1*time.Second, func() {
						if err := l.Load(); err != nil {
							log.Error(err, "Failed to reload feature gates")
						} else {
							log.Info("Feature gates reloaded successfully")
						}
					})
				}

			case err, ok := <-watcher.Errors:
				if !ok {
					return
				}
				log.Error(err, "Feature gates watcher error")
			}
		}
	}()

	return nil
}

// OnChange registers a callback for feature gate changes.
func (l *FeatureGateLoader) OnChange(cb func(*FeatureGates)) {
	l.onChange = append(l.onChange, cb)
}

// logFeatureGates logs feature gate settings with a visible banner.
func logFeatureGates(fg *FeatureGates, source string) {
	log.Info("============= FEATURE GATES ================")
	log.Info("[feature-gates] source", "source", source)
	log.Info("[feature-gates] gates",
		"globalEnabled", fg.GlobalEnabled,
		"envoyProxy", fg.EnvoyProxy,
		"spiffeHelper", fg.SpiffeHelper,
		"clientRegistration", fg.ClientRegistration,
	)
	log.Info("=============================================")
}
