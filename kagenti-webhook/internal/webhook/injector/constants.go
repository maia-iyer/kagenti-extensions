package injector

// Label constants used by the precedence evaluator.
// These are the per-sidecar workload labels and namespace injection label
// that control the injection precedence chain.
const (
	// Per-sidecar workload labels — set value to "false" to disable injection
	LabelEnvoyProxyInject         = "kagenti.io/envoy-proxy-inject"
	LabelSpiffeHelperInject       = "kagenti.io/spiffe-helper-inject"
	LabelClientRegistrationInject = "kagenti.io/client-registration-inject"

	// Namespace label for injection opt-in (used by precedence evaluator)
	LabelNamespaceInject = "kagenti-enabled"
)
