package config

// FeatureGates controls which sidecars are globally enabled/disabled.
// This is the highest-priority layer in the injection precedence chain.
type FeatureGates struct {
	GlobalEnabled      bool `json:"globalEnabled" yaml:"globalEnabled"`
	EnvoyProxy         bool `json:"envoyProxy" yaml:"envoyProxy"`
	SpiffeHelper       bool `json:"spiffeHelper" yaml:"spiffeHelper"`
	ClientRegistration bool `json:"clientRegistration" yaml:"clientRegistration"`
}

// DefaultFeatureGates returns feature gates with everything enabled.
func DefaultFeatureGates() *FeatureGates {
	return &FeatureGates{
		GlobalEnabled:      true,
		EnvoyProxy:         true,
		SpiffeHelper:       true,
		ClientRegistration: true,
	}
}

// DeepCopy creates a copy of the feature gates.
func (fg *FeatureGates) DeepCopy() *FeatureGates {
	if fg == nil {
		return nil
	}
	result := *fg
	return &result
}
