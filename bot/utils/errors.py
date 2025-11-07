class BotError(Exception):
    """Базовое исключение бота."""

class DataSourceError(BotError):
    """Ошибка при получении данных с внешнего API."""
