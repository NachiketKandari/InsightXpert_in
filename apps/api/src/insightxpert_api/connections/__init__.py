"""External DB connection support — encryption, typed configs, connectors.

Used by the BYO-DB feature: users plug in their own Postgres / libSQL / SQLite
endpoints; credentials are encrypted at rest in the ``databases`` registry and
the connector dispatch picks the right backend at query time.
"""
