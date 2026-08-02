# Confluence adapter

Confluence-specific code is isolated under `confluence/`. Conversion is warning-producing and provider state lives in `.work-smarter/sync/confluence/`; source documents remain authoritative. `ConfluencePublishingService` depends on a small client protocol, so fake transports can test sync without network access.
