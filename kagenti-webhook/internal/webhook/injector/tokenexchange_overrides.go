package injector

// TokenExchangeOverrides represents the per-sidecar enable/disable settings
// extracted from a TokenExchange CR for a specific workload.
// nil pointer fields mean "not specified" (fall through to lower layers).
//
// This is a stub — TokenExchange CR support is not yet implemented.
// Pass nil for tokenExchangeOverrides to skip this layer entirely.
type TokenExchangeOverrides struct {
	EnvoyProxy         *bool
	SpiffeHelper       *bool
	ClientRegistration *bool
}
