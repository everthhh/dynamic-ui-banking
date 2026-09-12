-- ============================================================================
-- dynamic-ui-banking · simulacion de la base de datos del banco
-- ----------------------------------------------------------------------------
-- SQLite. Todo sintetico y generado con semilla fija (ver bank/seed.py).
-- No hay ni un dato real de cliente. Los campos tipo RFC/CLABE/ISIN son
-- placeholders con formato valido pero contenido inventado, marcados *_mock.
--
-- Dos mitades:
--   core bancario  -> clientes, cuentas, movimientos, tarjetas, creditos
--   inversiones    -> instrumentos, series historicas, posiciones, ordenes
--
-- La mitad de inversiones es la que alimenta el demo; el core esta completo
-- para poder abrir los dominios de gasto y credito sin rehacer el esquema.
-- ============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---------------------------------------------------------------- core: gente
CREATE TABLE clients (
    client_id            TEXT PRIMARY KEY,          -- 'CLI-0001'
    nombre               TEXT    NOT NULL,
    fecha_alta           TEXT    NOT NULL,          -- ISO date
    segmento             TEXT    NOT NULL,          -- nomina | preferente | patrimonial | pyme
    ciudad               TEXT    NOT NULL,
    rfc_mock             TEXT    NOT NULL,
    ingreso_mensual      REAL    NOT NULL,          -- MXN declarado
    horizonte_meses      INTEGER,                   -- lo que el cliente dijo la ultima vez
    CHECK (segmento IN ('nomina','preferente','patrimonial','pyme'))
);

-- ------------------------------------------------------------- core: cuentas
CREATE TABLE accounts (
    account_id           TEXT PRIMARY KEY,          -- 'ACC-0001'
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    tipo                 TEXT    NOT NULL,          -- cheques | ahorro | nomina | inversion
    clabe_mock           TEXT    NOT NULL,
    moneda               TEXT    NOT NULL DEFAULT 'MXN',
    saldo_disponible     REAL    NOT NULL DEFAULT 0,
    saldo_liquidado      REAL    NOT NULL DEFAULT 0,
    abierta_en           TEXT    NOT NULL,
    CHECK (tipo IN ('cheques','ahorro','nomina','inversion')),
    CHECK (moneda IN ('MXN','USD'))
);
CREATE INDEX idx_accounts_client ON accounts(client_id);

-- --------------------------------------------------------- core: movimientos
CREATE TABLE transactions (
    txn_id               TEXT PRIMARY KEY,          -- 'TXN-000001'
    account_id           TEXT    NOT NULL REFERENCES accounts(account_id),
    fecha                TEXT    NOT NULL,          -- ISO datetime
    tipo                 TEXT    NOT NULL,          -- cargo | abono
    monto                REAL    NOT NULL,          -- siempre positivo; el signo lo da `tipo`
    categoria            TEXT    NOT NULL,          -- nomina | renta | super | transporte | ...
    descripcion          TEXT    NOT NULL,
    comercio             TEXT,
    saldo_posterior      REAL    NOT NULL,
    CHECK (tipo IN ('cargo','abono')),
    CHECK (monto >= 0)
);
CREATE INDEX idx_txn_account_fecha ON transactions(account_id, fecha DESC);
CREATE INDEX idx_txn_categoria     ON transactions(categoria);

-- ------------------------------------------------------------ core: tarjetas
CREATE TABLE cards (
    card_id              TEXT PRIMARY KEY,
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    account_id           TEXT             REFERENCES accounts(account_id),
    tipo                 TEXT    NOT NULL,          -- debito | credito
    last4                TEXT    NOT NULL,
    limite_credito       REAL,
    saldo_utilizado      REAL    NOT NULL DEFAULT 0,
    dia_corte            INTEGER,
    dia_pago             INTEGER,
    CHECK (tipo IN ('debito','credito'))
);
CREATE INDEX idx_cards_client ON cards(client_id);

-- ------------------------------------------------------------- core: credito
CREATE TABLE loans (
    loan_id              TEXT PRIMARY KEY,
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    producto             TEXT    NOT NULL,          -- auto | hipotecario | personal | nomina
    monto_original       REAL    NOT NULL,
    saldo_insoluto       REAL    NOT NULL,
    tasa_anual           REAL    NOT NULL,
    plazo_meses          INTEGER NOT NULL,
    pago_mensual         REAL    NOT NULL,
    mensualidades_pagadas INTEGER NOT NULL DEFAULT 0,
    abierto_en           TEXT    NOT NULL,
    CHECK (producto IN ('auto','hipotecario','personal','nomina'))
);
CREATE INDEX idx_loans_client ON loans(client_id);

-- ------------------------------------------------- inversiones: instrumentos
CREATE TABLE instruments (
    instrument_id        TEXT PRIMARY KEY,          -- 'CETES-28', 'FND-RV-GLOBAL'
    nombre               TEXT    NOT NULL,
    clase                TEXT    NOT NULL,          -- deuda_gub | deuda_corp | renta_variable
                                                    -- | fondo_deuda | fondo_rv | etf | pagare
    emisor               TEXT    NOT NULL,
    moneda               TEXT    NOT NULL DEFAULT 'MXN',
    rend_esperado_anual  REAL    NOT NULL,          -- nominal, decimal (0.095 = 9.5%)
    volatilidad_anual    REAL    NOT NULL,          -- desviacion estandar, decimal
    comision_anual       REAL    NOT NULL DEFAULT 0,
    plazo_dias           INTEGER,                   -- NULL = sin plazo forzoso
    liquidez             TEXT    NOT NULL,          -- diaria | 24h | 48h | al_vencimiento
    monto_minimo         REAL    NOT NULL DEFAULT 100,
    riesgo_1a5           INTEGER NOT NULL,          -- 1 muy bajo ... 5 muy alto
    isin_mock            TEXT    NOT NULL,
    descripcion          TEXT    NOT NULL,
    CHECK (clase IN ('deuda_gub','deuda_corp','renta_variable',
                     'fondo_deuda','fondo_rv','etf','pagare')),
    CHECK (liquidez IN ('diaria','24h','48h','al_vencimiento')),
    CHECK (riesgo_1a5 BETWEEN 1 AND 5)
);
CREATE INDEX idx_instruments_clase  ON instruments(clase);
CREATE INDEX idx_instruments_riesgo ON instruments(riesgo_1a5);

-- Series mensuales de 10 anos por instrumento (GBM correlacionado por clase).
CREATE TABLE instrument_series (
    instrument_id        TEXT    NOT NULL REFERENCES instruments(instrument_id),
    fecha                TEXT    NOT NULL,          -- ISO date, fin de mes
    valor_unitario       REAL    NOT NULL,          -- base 100 en el primer mes
    rend_mensual         REAL    NOT NULL,          -- decimal
    PRIMARY KEY (instrument_id, fecha)
);

-- ------------------------------------------------------ inversiones: cartera
CREATE TABLE risk_profiles (
    profile_id           TEXT PRIMARY KEY,
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    score                INTEGER NOT NULL,          -- 0..100
    perfil               TEXT    NOT NULL,          -- conservador | moderado | balanceado
                                                    -- | crecimiento | agresivo
    horizonte_meses      INTEGER NOT NULL,
    respondido_en        TEXT    NOT NULL,
    vigente_hasta        TEXT    NOT NULL,
    answers_json         TEXT    NOT NULL,
    CHECK (score BETWEEN 0 AND 100),
    CHECK (perfil IN ('conservador','moderado','balanceado','crecimiento','agresivo'))
);
CREATE INDEX idx_profiles_client ON risk_profiles(client_id, vigente_hasta DESC);

CREATE TABLE positions (
    position_id          TEXT PRIMARY KEY,
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    account_id           TEXT    NOT NULL REFERENCES accounts(account_id),
    instrument_id        TEXT    NOT NULL REFERENCES instruments(instrument_id),
    titulos              REAL    NOT NULL,
    costo_promedio       REAL    NOT NULL,          -- por titulo
    abierta_en           TEXT    NOT NULL,
    UNIQUE (account_id, instrument_id)
);
CREATE INDEX idx_positions_client ON positions(client_id);

-- ------------------------------------------------------- inversiones: ordenes
CREATE TABLE orders (
    order_id             TEXT PRIMARY KEY,          -- uuid
    folio                TEXT    NOT NULL UNIQUE,   -- 'BN-2026-000123' (lo ve el cliente)
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    account_id           TEXT    NOT NULL REFERENCES accounts(account_id),
    estado               TEXT    NOT NULL,          -- pendiente | ejecutada | rechazada | cancelada
    monto                REAL    NOT NULL,
    motivo_rechazo       TEXT,
    creada_en            TEXT    NOT NULL,
    ejecutada_en         TEXT,
    idempotency_key      TEXT    NOT NULL,          -- evita duplicados por reintento del modelo
                                                    -- unicidad es por (client_id, idempotency_key),
                                                    -- no global: ver UNIQUE mas abajo
    confirmation_token_hash TEXT NOT NULL,          -- sha256 del token; el token crudo nunca se
                                                    -- guarda, solo se entrega una vez al crear
    CHECK (estado IN ('pendiente','ejecutando','ejecutada','rechazada','cancelada')),
    CHECK (monto > 0),
    UNIQUE (client_id, idempotency_key)
);
CREATE INDEX idx_orders_client ON orders(client_id, creada_en DESC);

CREATE TABLE order_legs (
    order_id             TEXT    NOT NULL REFERENCES orders(order_id),
    instrument_id        TEXT    NOT NULL REFERENCES instruments(instrument_id),
    peso                 REAL    NOT NULL,          -- 0..1, suma 1 por orden
    monto                REAL    NOT NULL,
    titulos              REAL    NOT NULL,
    PRIMARY KEY (order_id, instrument_id),
    CHECK (peso >= 0 AND peso <= 1)
);

-- ----------------------------------------------------- bitacora del blueprint
-- Cada superficie que el agente emite queda registrada con el turno y las
-- tools que se llamaron. Sirve para reconstruir la sesion y para la auditoria
-- que pide la rubrica (§07 del marco tecnico).
CREATE TABLE surface_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT    NOT NULL,
    turn                 INTEGER NOT NULL,
    surface_id           TEXT    NOT NULL,
    messages_json        TEXT    NOT NULL,          -- los mensajes A2UI emitidos
    tools_json           TEXT    NOT NULL,          -- [{name, input, output_digest}]
    created_at           TEXT    NOT NULL
);
CREATE INDEX idx_surface_log_session ON surface_log(session_id, turn);

-- Parametros de mercado que usan las simulaciones. Una sola fila.
CREATE TABLE market_params (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    fecha_valuacion      TEXT    NOT NULL,
    tasa_libre_riesgo    REAL    NOT NULL,          -- CETES 28d sintetico
    inflacion_anual      REAL    NOT NULL,
    seed                 INTEGER NOT NULL
);
