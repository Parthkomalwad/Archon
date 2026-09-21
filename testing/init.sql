-- Seed script  runs automatically when the postgres container starts for the first time.
-- Creates two tables with sample data so there is something worth backing up.

CREATE TABLE users (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(100) NOT NULL,
    email   VARCHAR(100) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE products (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(100) NOT NULL,
    price   DECIMAL(10,2) NOT NULL,
    stock   INT DEFAULT 0
);

INSERT INTO users (name, email) VALUES
    ('Alice Smith',    'alice@example.com'),
    ('Bob Jones',      'bob@example.com'),
    ('Charlie Brown',  'charlie@example.com');

INSERT INTO products (name, price, stock) VALUES
    ('Widget A',   9.99,   100),
    ('Widget B',   24.99,   50),
    ('Gadget Pro', 149.99,  25);
