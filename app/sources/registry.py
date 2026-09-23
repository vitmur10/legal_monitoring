from app.sources.base import SourceAdapter


class SourceRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        self._adapters[adapter.source_code] = adapter

    def get(self, source_code: str) -> SourceAdapter:
        try:
            return self._adapters[source_code]
        except KeyError as exc:
            raise KeyError(f"No source adapter registered for {source_code!r}") from exc

    def all(self) -> list[SourceAdapter]:
        return list(self._adapters.values())


registry = SourceRegistry()
