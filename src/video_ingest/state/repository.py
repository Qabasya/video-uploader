"""Repository над SQLite: единственная точка доступа к ``state.db``."""


class StateRepository:
    """Реестр файлов и переходы статусов (WAL; заглушка этапа 3)."""
