# Задание 2. История покупок

Выбран CQRS: отдельный сервис истории строит модель чтения по снимкам заказов и по новому снимку платежа с ключами чеков. Рассмотренные альтернативы — модель чтения внутри сервиса заказов, API Composition и Event Sourcing.

- [ADR-order-history.md](ADR-order-history.md) — ADR: выбор CQRS для истории покупок, альтернативы и риски.
- [c2-containers.png](c2-containers.png) — обновлённая схема C2 целиком, исходник [c2-containers.puml](c2-containers.puml).
- [c2-history.png](c2-history.png) — срез C2 по сценарию истории покупок, исходник [c2-history.puml](c2-history.puml).
- [c1-context.png](c1-context.png) — контекст системы для ADR, исходник [c1-context.puml](c1-context.puml).
