# db.py
import psycopg2
from psycopg2 import extras
from psycopg2.pool import ThreadedConnectionPool
from functools import lru_cache
from config import logger, DATABASE_URL

class Database:
    __slots__ = ['pool']

    def __init__(self):
        try:
            self.pool = ThreadedConnectionPool(1, 10, DATABASE_URL)
            logger.info("Connection pool created")
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    self.create_tables(cursor)
                    conn.commit()
            logger.info("Connected to PostgreSQL database")
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            raise

    def get_connection(self):
        return self.pool.getconn()

    def put_connection(self, conn):
        self.pool.putconn(conn)

    def create_tables(self, cursor):
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    user_id BIGINT PRIMARY KEY,
                    organization TEXT NOT NULL,
                    contact_person TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS orders (
                    order_id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    order_data JSONB,
                    delivery_date TEXT,
                    delivery_time TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_orders_delivery_date ON orders (delivery_date);
                CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders (user_id);
            """)
            logger.info("Database tables initialized successfully")
        except Exception as e:
            logger.error(f"Error creating tables: {e}")
            raise

    @lru_cache(maxsize=100)
    def get_client(self, user_id: int):
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute("SELECT organization, contact_person FROM clients WHERE user_id = %s", (user_id,))
                result = cursor.fetchone()
                return (result['organization'], result['contact_person']) if result else (None, None)
        except Exception as e:
            logger.error(f"Error fetching client {user_id}: {e}")
            return None, None
        finally:
            self.put_connection(conn)

    def add_client(self, user_id: int, organization: str, contact_person: str):
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO clients (user_id, organization, contact_person) VALUES (%s, %s, %s)",
                    (user_id, organization, contact_person)
                )
                conn.commit()
            logger.info(f"Client {user_id} added: {organization}, {contact_person}")
        except Exception as e:
            logger.error(f"Error adding client {user_id}: {e}")
            conn.rollback()
        finally:
            self.put_connection(conn)

    def get_all_clients(self):
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute("SELECT user_id, organization, contact_person FROM clients")
                return {row['user_id']: (row['organization'], row['contact_person']) for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Error fetching all clients: {e}")
            return {}
        finally:
            self.put_connection(conn)

    def save_order(self, user_id: int, order_data: Dict[str, Any], delivery_date: str, delivery_time: str) -> int:
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    INSERT INTO orders (user_id, order_data, delivery_date, delivery_time)
                    VALUES (%s, %s, %s, %s)
                    RETURNING order_id
                ''', (user_id, json.dumps(order_data), delivery_date, delivery_time))
                order_id = cursor.fetchone()[0]
                conn.commit()
                return order_id
        except Exception as e:
            logger.error(f"Error saving order for user {user_id}: {e}")
            conn.rollback()
            raise
        finally:
            self.put_connection(conn)

    def cancel_order(self, order_id: int) -> bool:
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute('''
                    UPDATE orders 
                    SET status = 'cancelled' 
                    WHERE order_id = %s AND status = 'active'
                ''', (order_id,))
                rows_affected = cursor.rowcount
                conn.commit()
                return rows_affected > 0
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            conn.rollback()
            return False
        finally:
            self.put_connection(conn)

    def get_active_order(self, user_id: int):
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                    SELECT order_id, order_data, delivery_date, delivery_time 
                    FROM orders 
                    WHERE user_id = %s AND status = 'active'
                    ORDER BY created_at DESC 
                    LIMIT 1
                ''', (user_id,))
                result = cursor.fetchone()
                if result:
                    return {
                        'order_id': result['order_id'],
                        'order_data': result['order_data'],
                        'delivery_date': result['delivery_date'],
                        'delivery_time': result['delivery_time']
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting active order for user {user_id}: {e}")
            return None
        finally:
            self.put_connection(conn)

    def get_order(self, order_id: int):
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute('''
                    SELECT order_id, user_id, order_data, delivery_date, delivery_time, status 
                    FROM orders 
                    WHERE order_id = %s
                ''', (order_id,))
                result = cursor.fetchone()
                if result:
                    return {
                        'order_id': result['order_id'],
                        'user_id': result['user_id'],
                        'order_data': result['order_data'],
                        'delivery_date': result['delivery_date'],
                        'delivery_time': result['delivery_time'],
                        'status': result['status']
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting order {order_id}: {e}")
            return None
        finally:
            self.put_connection(conn)

    def get_orders_for_date(self, date_str: str) -> list:
        conn = self.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.DictCursor) as cursor:
                cursor.execute("""
                    SELECT order_id, user_id, order_data, delivery_date, delivery_time 
                    FROM orders 
                    WHERE delivery_date = %s AND status = 'active'
                """, (date_str,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error fetching orders for date {date_str}: {e}")
            return []
        finally:
            self.put_connection(conn)

    def close(self):
        self.pool.closeall()
        logger.info("Database connection pool closed")