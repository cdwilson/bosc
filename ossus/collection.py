import json
import re
import uuid
from enum import Enum
from typing import Optional, Dict, List, Union

from ossus.index import Index, IndexType
from ossus.queries.base import Query, UpdateOperation


class OrderDirection(str, Enum):
    ASC = "ASC"
    DESC = "DESC"


class Collection:
    def __init__(self, collection_name, connection, database):
        self.connection = connection
        self.collection_name = collection_name
        self.database = database
        self._create_table()

    def _create_table(self):
        self.connection.execute(f'CREATE TABLE IF NOT EXISTS {self.collection_name} (id INTEGER PRIMARY KEY, data JSON)')
        self.connection.commit()
        self.create_index(Index(IndexType.PATH, "id"))

    def insert(self, document: dict):
        # if there is no id, it will be auto-generated
        if 'id' not in document:
            document['id'] = uuid.uuid4().hex
        self.connection.execute(f'INSERT INTO {self.collection_name} (data) VALUES (json(?))', [json.dumps(document)])
        self.connection.commit()
        return document['id']

    def insert_many(self, documents: list):
        documents_as_json = [(json.dumps(doc),) for doc in documents]
        self.connection.executemany(f'INSERT INTO {self.collection_name} (data) VALUES (json(?))', documents_as_json)
        self.connection.commit()

    def find(self, query: Optional[Query] = None, order_by: str = None,
             order_direction: OrderDirection = OrderDirection.ASC) -> List[
        Dict]:
        cursor = self.connection.cursor()
        if query:
            where_clause, query_val = query.to_sql()
            sql = f"SELECT data FROM {self.collection_name} WHERE {where_clause}"
        else:
            sql = f"SELECT data FROM {self.collection_name}"
            query_val = ()
        if order_by:
            sql += f" ORDER BY json_extract(data, '$.{order_by}') {order_direction}"
        cursor.execute(sql, query_val)
        return [json.loads(row[0]) for row in cursor.fetchall()]

    def find_one(self, query: Optional[Query] = None, order_by: str = None,
                 order_direction: OrderDirection = OrderDirection.ASC) -> \
            Optional[Dict]:
        cursor = self.connection.cursor()

        if query:
            where_clause, query_params = query.to_sql()
            sql = f"SELECT data FROM {self.collection_name} WHERE {where_clause}"
        else:
            sql = f"SELECT data FROM {self.collection_name}"
            query_params = []
        if order_by:
            sql += f" ORDER BY json_extract(data, '$.{order_by}') {order_direction}"
        sql += " LIMIT 1"

        cursor.execute(sql, query_params)
        row = cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None

    from typing import Optional

    def update(self, query: Optional[Query] = None, *operations: UpdateOperation):
        cursor = self.connection.cursor()

        # Initialize where_clause and query_params
        where_clause, query_params = ("", [])
        if query:
            # Convert query to SQL only if query is not None
            where_clause, query_params = query.to_sql()
            where_clause = f"WHERE {where_clause}"  # Prefix with WHERE only if there's a query

        # Prepare SQL update expressions and parameters from operations
        update_expressions = []
        update_params = []
        for op in operations:
            sql_part, params = op.to_sql_update()
            update_expressions.append(sql_part)
            update_params.extend(params)

        # Combine update expressions into a single SQL statement
        update_sql = ", ".join(update_expressions)
        if where_clause:
            sql = f"UPDATE {self.collection_name} SET data = {update_sql} {where_clause}"
        else:
            sql = f"UPDATE {self.collection_name} SET data = {update_sql}"

        # Execute the update query with the combined parameters (if any)
        if query_params:
            cursor.execute(sql, update_params + query_params)
        else:
            cursor.execute(sql, update_params)
        self.connection.commit()

    def update_one(self, query: Optional[Query] = None, *operations: UpdateOperation, order_by: str = None,
                   order_direction: str = "ASC"):
        cursor = self.connection.cursor()

        # Initialize where_clause and query_params
        where_clause, query_params = ("", [])
        if query:
            # Convert query to SQL only if query is not None
            where_clause, query_params = query.to_sql()
            where_clause = f"WHERE {where_clause}"  # Prefix with WHERE only if there's a query

        # Prepare SQL update expressions and parameters from operations
        update_expressions = []
        update_params = []
        for op in operations:
            sql_part, params = op.to_sql_update()
            update_expressions.append(sql_part)
            update_params.extend(params)

        # Combine update expressions into a single SQL statement
        update_sql = ", ".join(update_expressions)
        sql = f"UPDATE {self.collection_name} SET data = {update_sql} {where_clause}"

        # SQLite does not support ORDER BY in UPDATE statements directly.
        # If ordering is crucial for your logic, consider a workaround or adjusting your database design.
        # This example does not implement ORDER BY due to SQLite's limitations.
        sql += " LIMIT 1"

        # Execute the update query with the combined parameters (if any)
        if query_params:
            cursor.execute(sql, update_params + query_params)
        else:
            cursor.execute(sql, update_params)
        self.connection.commit()

    def delete(self, query: Optional[Query] = None):
        cursor = self.connection.cursor()
        if query:
            where_clause, query_val = query.to_sql()
            sql = f"DELETE FROM {self.collection_name} WHERE {where_clause}"
        else:
            sql = f"DELETE FROM {self.collection_name}"
            query_val = ()
        cursor.execute(sql, query_val)
        self.connection.commit()

    def delete_one(self, query: Optional[Query] = None, order_by: str = None,
                   order_direction: OrderDirection = OrderDirection.ASC):
        cursor = self.connection.cursor()
        if query:
            where_clause, query_val = query.to_sql()
            sql = f"DELETE FROM {self.collection_name} WHERE {where_clause}"
        else:
            sql = f"DELETE FROM {self.collection_name}"
            query_val = ()

        if order_by:
            sql += f" ORDER BY json_extract(data, '$.{order_by}') {order_direction}"
        sql += " LIMIT 1"

        cursor.execute(sql, query_val)
        self.connection.commit()

    # Indexes

    def get_indexes(self) -> List[Index]:
        indexes = []
        cursor = self.connection.cursor()
        cursor.execute(
            f"SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='{self.collection_name}' AND sql NOT NULL order by name")
        for name, sql in cursor.fetchall():
            index_type = Index.extract_type(sql)
            index_value = Index.extract_value(sql)
            indexes.append(Index(index_type, index_value, name))

        return indexes

    def create_index(self, index):
        index_name_quoted = f'"{index.name}"'
        collection_name_quoted = f'"{self.collection_name}"'

        if index.index_type == IndexType.PATH:
            index_sql = f"CREATE INDEX IF NOT EXISTS {index_name_quoted} ON {collection_name_quoted} (json_extract(data, '$.{index.value}'))"
        elif index.index_type == IndexType.PARTIAL:
            index_sql = f"CREATE INDEX IF NOT EXISTS {index_name_quoted} ON {collection_name_quoted} (json_extract(data, '$.id')) WHERE {index.value}"
        else:
            index_sql = f"CREATE INDEX IF NOT EXISTS {index_name_quoted} ON {collection_name_quoted} ({index.value})"

        self.connection.execute(index_sql)
        self.connection.commit()

    def drop_index(self, index: Union[str, Index]):
        if isinstance(index, str):
            self.connection.execute(f"DROP INDEX IF EXISTS {index}")
        else:
            indexes = self.get_indexes()
            for idx in indexes:
                if idx == index:
                    self.connection.execute(f"DROP INDEX IF EXISTS {idx.name}")
                    break
        self.connection.commit()

    def drop_all_indexes(self):
        indexes = self.get_indexes()
        for index in indexes:
            self.drop_index(index)
        self.connection.commit()