-- ============================================================================
-- dynamic-ui-banking · simulacion de la base de datos del banco
-- ----------------------------------------------------------------------------
-- SQLite. Todo sintetico y generado con semilla fija (ver bank/seed.py).
-- No hay ni un dato real de cliente. Los campos tipo RFC/CLABE/ISIN son
-- placeholders con formato valido pero contenido inventado, marcados *_mock.
--
-- Tres partes:
--   core bancario  -> clientes, cuentas, movimientos, tarjetas, creditos
--   inversiones    -> instrumentos, series historicas, posiciones, ordenes
--   pagos          -> convenios, servicios y recibos, contactos, operaciones,
--                     dinero recibido, referencias de deposito
--
-- Las CLABEs mock llevan digito verificador valido (algoritmo de Banxico): el
-- dominio de pagos las valida igual que valida las que teclea el usuario.
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
    -- conocimiento del cliente (KYC): lo que el banco pide al abrir la cuenta
    fecha_nacimiento     TEXT,                      -- ISO date
    ocupacion            TEXT,
    dependientes         INTEGER NOT NULL DEFAULT 0,
    CHECK (segmento IN ('nomina','preferente','patrimonial','pyme'))
);

-- ------------------------------------------------------------- core: cuentas
CREATE TABLE accounts (
    account_id           TEXT PRIMARY KEY,          -- 'ACC-0001'
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    tipo                 TEXT    NOT NULL,          -- cheques | ahorro | nomina | inversion
    alias                TEXT,                      -- apodo del cliente, ej. 'Mi cuenta del super'
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
-- Un solo libro por cliente, como lo ve en la app: la cuenta de uso y su
-- tarjeta de credito. `card_id` NULL = movimiento de la cuenta; con valor =
-- compra, interes o comision de esa tarjeta (y `account_id` es su cuenta eje).
-- Categorias (ver bank/categorias.py):
--   consumo      super | restaurantes | transporte | servicios | renta | salud
--                | entretenimiento | educacion
--   ingreso      nomina | honorarios
--   no consumo   traspaso | inversion | pago_tarjeta | credito | costo_financiero
CREATE TABLE transactions (
    txn_id               TEXT PRIMARY KEY,          -- 'TXN-000001'
    account_id           TEXT    NOT NULL REFERENCES accounts(account_id),
    card_id              TEXT             REFERENCES cards(card_id),
    fecha                TEXT    NOT NULL,          -- ISO datetime
    tipo                 TEXT    NOT NULL,          -- cargo | abono
    monto                REAL    NOT NULL,          -- siempre positivo; el signo lo da `tipo`
    categoria            TEXT    NOT NULL,
    descripcion          TEXT    NOT NULL,
    comercio             TEXT,
    saldo_posterior      REAL    NOT NULL,          -- del producto que se movio: cuenta o tarjeta
    CHECK (tipo IN ('cargo','abono')),
    CHECK (monto >= 0)
);
CREATE INDEX idx_txn_account_fecha ON transactions(account_id, fecha DESC);
CREATE INDEX idx_txn_categoria     ON transactions(categoria);
CREATE INDEX idx_txn_card          ON transactions(card_id);

-- ------------------------------------------------------------ core: tarjetas
CREATE TABLE cards (
    card_id              TEXT PRIMARY KEY,
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    account_id           TEXT             REFERENCES accounts(account_id),
    tipo                 TEXT    NOT NULL,          -- debito | credito
    alias                TEXT,                      -- ej. 'Platino viajes'
    last4                TEXT    NOT NULL,
    estado               TEXT    NOT NULL DEFAULT 'activa',   -- activa | bloqueada
    limite_credito       REAL,
    saldo_utilizado      REAL    NOT NULL DEFAULT 0,
    tasa_anual           REAL,                      -- CAT aproximado; NULL en debito
    dia_corte            INTEGER,
    dia_pago             INTEGER,
    CHECK (tipo IN ('debito','credito')),
    CHECK (estado IN ('activa','bloqueada'))
);
CREATE INDEX idx_cards_client ON cards(client_id);

-- Auditoria de acciones sobre una tarjeta (bloqueo, limite, alias). Cada
-- mutacion de banca personal deja rastro, igual que `surface_log` para el
-- blueprint: es lo que permite reconstruir "quien cambio que y cuando" sin
-- confiar en la memoria de la sesion.
CREATE TABLE card_events (
    event_id             TEXT PRIMARY KEY,
    card_id              TEXT    NOT NULL REFERENCES cards(card_id),
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    tipo                 TEXT    NOT NULL,          -- bloqueo | desbloqueo | limite | alias
    detalle_json         TEXT    NOT NULL,
    creado_en            TEXT    NOT NULL,
    CHECK (tipo IN ('bloqueo','desbloqueo','limite','alias'))
);
CREATE INDEX idx_card_events_card ON card_events(card_id, creado_en DESC);

-- Estados de cuenta mensuales de tarjeta de credito: el historial crediticio
-- interno. Cuanto debia al corte, cuanto era el minimo, cuanto pago y cuando.
-- `bank/finance/perfil.py` deduce de aqui si el cliente es totalero,
-- revolvente o paga tarde; ninguna de esas etiquetas se guarda.
CREATE TABLE card_statements (
    statement_id         TEXT PRIMARY KEY,
    card_id              TEXT    NOT NULL REFERENCES cards(card_id),
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    fecha_corte          TEXT    NOT NULL,          -- ISO date
    fecha_limite_pago    TEXT    NOT NULL,
    saldo_anterior       REAL    NOT NULL,
    compras              REAL    NOT NULL,
    intereses            REAL    NOT NULL DEFAULT 0,
    comisiones           REAL    NOT NULL DEFAULT 0,
    pagos_periodo        REAL    NOT NULL DEFAULT 0,
    saldo_al_corte       REAL    NOT NULL,
    pago_minimo          REAL    NOT NULL,
    pago_no_intereses    REAL    NOT NULL,
    pagado               REAL    NOT NULL DEFAULT 0, -- abonado a ESTE corte
    fecha_pago           TEXT,                       -- NULL: no ha pagado
    dias_atraso          INTEGER NOT NULL DEFAULT 0,
    CHECK (saldo_al_corte >= 0),
    CHECK (pagado >= 0),
    CHECK (dias_atraso >= 0)
);
CREATE INDEX idx_statements_card   ON card_statements(card_id, fecha_corte DESC);
CREATE INDEX idx_statements_client ON card_statements(client_id, fecha_corte DESC);

-- ---------------------------------------------------------- core: presupuestos
-- Uno por categoria y cliente: el usuario define cuanto quiere gastar al mes
-- en 'super', 'transporte', etc. `get_spending_alerts` compara esto contra
-- el gasto real del mes.
CREATE TABLE budgets (
    budget_id            TEXT PRIMARY KEY,
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    categoria            TEXT    NOT NULL,
    monto_mensual        REAL    NOT NULL,
    creado_en            TEXT    NOT NULL,
    actualizado_en       TEXT    NOT NULL,
    UNIQUE (client_id, categoria),
    CHECK (monto_mensual > 0)
);
CREATE INDEX idx_budgets_client ON budgets(client_id);

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

-- --------------------------------------------------- inversiones: emisoras
-- Empresas listadas en la BMV. NO son contratables: esto es un producto de
-- fondos, y el cliente llega a estas empresas a traves de lo que los fondos
-- traen en cartera (ver `fund_holdings`). Estan aqui porque de estas columnas
-- se CALCULA el riesgo, en bank/emisoras.py; no es un numero escrito a mano.
CREATE TABLE issuers (
    ticker               TEXT PRIMARY KEY,          -- 'WALMEX', 'GFNORTEO'
    nombre               TEXT    NOT NULL,
    sector               TEXT    NOT NULL,
    precio               REAL    NOT NULL,          -- MXN por titulo
    fuente_precio        TEXT    NOT NULL,          -- anclado | estimado
    fecha_precio         TEXT    NOT NULL,          -- ISO date de la foto
    acciones_circulacion REAL    NOT NULL,          -- millones de titulos
    capitalizacion_mdp   REAL    NOT NULL,          -- millones de MXN
    float_pct            REAL    NOT NULL,
    beta                 REAL    NOT NULL,          -- vs S&P/BMV IPC
    volatilidad_anual    REAL    NOT NULL,
    dividend_yield       REAL    NOT NULL,
    calificacion         TEXT    NOT NULL,          -- escala nacional (mxAAA...)
    deuda_neta_ebitda    REAL,                      -- NULL en financieras
    cobertura_intereses  REAL,
    indice_capitalizacion REAL,                     -- ICAP, solo financieras
    importe_operado_mdp  REAL    NOT NULL,          -- promedio diario
    r_cuadrada           REAL    NOT NULL,          -- varianza explicada por el IPC
    score_riesgo         REAL    NOT NULL,          -- 0-100, calculado
    riesgo_1a5           INTEGER NOT NULL,
    descripcion          TEXT    NOT NULL,
    CHECK (fuente_precio IN ('anclado','estimado')),
    CHECK (riesgo_1a5 BETWEEN 1 AND 5),
    CHECK (float_pct > 0 AND float_pct <= 1)
);
CREATE INDEX idx_issuers_sector ON issuers(sector);

-- Desglose del score de riesgo de cada emisora: que factor aporto cuanto.
-- Existe para que la cifra sea auditable sin volver a correr el calculo.
CREATE TABLE issuer_risk_factors (
    ticker               TEXT    NOT NULL REFERENCES issuers(ticker),
    factor               TEXT    NOT NULL,          -- volatilidad | solvencia | ...
    valor                REAL    NOT NULL,          -- 0-100
    peso                 REAL    NOT NULL,
    aporte               REAL    NOT NULL,
    PRIMARY KEY (ticker, factor)
);

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
    regimen_fiscal       TEXT    NOT NULL DEFAULT 'interes',  -- interes | capital
    duracion_anios       REAL    NOT NULL DEFAULT 0,   -- golpe de precio si suben tasas
    sens_reinversion     REAL    NOT NULL DEFAULT 0,   -- cuanto se renueva a la tasa vigente
    riesgo_derivado      INTEGER NOT NULL DEFAULT 0,   -- 1 = sale de fund_holdings
    CHECK (clase IN ('deuda_gub','deuda_corp','renta_variable',
                     'fondo_deuda','fondo_rv','etf','pagare')),
    CHECK (regimen_fiscal IN ('interes','capital')),
    CHECK (liquidez IN ('diaria','24h','48h','al_vencimiento')),
    CHECK (riesgo_1a5 BETWEEN 1 AND 5)
);
CREATE INDEX idx_instruments_clase  ON instruments(clase);
CREATE INDEX idx_instruments_riesgo ON instruments(riesgo_1a5);

-- Composicion de los fondos que invierten en emisoras de la BMV.
-- Es la tabla que conecta "lo que el cliente compra" con "las empresas en las
-- que acaba su dinero". El look-through del portafolio se calcula desde aqui:
--   peso efectivo = peso del fondo en el portafolio * peso de la emisora aqui
-- Los fondos internacionales y sectoriales globales no aparecen: su subyacente
-- no son emisoras de la BMV y no se les inventa cartera.
CREATE TABLE fund_holdings (
    instrument_id        TEXT    NOT NULL REFERENCES instruments(instrument_id),
    ticker               TEXT    NOT NULL REFERENCES issuers(ticker),
    peso                 REAL    NOT NULL,             -- dentro del fondo, suma 1
    PRIMARY KEY (instrument_id, ticker),
    CHECK (peso > 0 AND peso <= 1)
);
CREATE INDEX idx_holdings_ticker ON fund_holdings(ticker);

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

-- ===================================================================== pagos
-- Tercer dominio. Catálogo de convenios, servicios guardados con su recibo,
-- contactos para transferir, y UNA sola tabla de operaciones (`payments`) para
-- todo lo que saca dinero de una cuenta fuera de inversiones: pago de
-- servicios, transferencias y retiros sin tarjeta. Mismos candados que
-- `orders`: nada se ejecuta sin `confirmation_token` (solo se guarda su hash)
-- e `idempotency_key` es única por cliente.

CREATE TABLE billers (
    biller_id            TEXT PRIMARY KEY,          -- 'CFE', 'TELMEX', 'SACMEX'
    nombre               TEXT    NOT NULL,
    categoria            TEXT    NOT NULL,          -- luz | agua | internet | telefonia | gas | television
    referencia_etiqueta  TEXT    NOT NULL,          -- 'Número de servicio (12 dígitos)'
    referencia_regex     TEXT    NOT NULL,
    fuente_formato       TEXT    NOT NULL,          -- publico | simulado
    cobertura            TEXT    NOT NULL,          -- 'nacional' o ciudades separadas por coma
    periodicidad         TEXT    NOT NULL,          -- mensual | bimestral
    comision             REAL    NOT NULL DEFAULT 0,
    CHECK (categoria IN ('luz','agua','internet','telefonia','gas','television')),
    CHECK (fuente_formato IN ('publico','simulado')),
    CHECK (periodicidad IN ('mensual','bimestral')),
    CHECK (comision >= 0)
);

-- Un servicio que el cliente ya registró: convenio + su referencia.
CREATE TABLE saved_services (
    service_id           TEXT PRIMARY KEY,
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    biller_id            TEXT    NOT NULL REFERENCES billers(biller_id),
    referencia           TEXT    NOT NULL,          -- número de servicio / teléfono / cuenta (mock)
    alias                TEXT,                      -- 'Luz de la casa'
    creado_en            TEXT    NOT NULL,
    UNIQUE (client_id, biller_id, referencia)
);
CREATE INDEX idx_saved_services_client ON saved_services(client_id);

-- Recibos. El vencido no se guarda: se calcula contra la fecha de valuación,
-- para que no exista un estado que envejezca sin que nadie lo actualice.
CREATE TABLE bills (
    bill_id              TEXT PRIMARY KEY,
    service_id           TEXT    NOT NULL REFERENCES saved_services(service_id),
    periodo              TEXT    NOT NULL,          -- 'ago 2026' | 'jul–ago 2026'
    monto                REAL    NOT NULL,
    fecha_emision        TEXT    NOT NULL,
    fecha_limite         TEXT    NOT NULL,
    estado               TEXT    NOT NULL DEFAULT 'pendiente',   -- pendiente | pagado
    payment_id           TEXT    REFERENCES payments(payment_id),
    CHECK (monto > 0),
    CHECK (estado IN ('pendiente','pagado'))
);
CREATE INDEX idx_bills_service ON bills(service_id, estado);

-- Contactos para transferir. `creado_en` importa: un destino registrado hace
-- menos de 30 minutos se trata como nuevo y tiene tope por operación.
CREATE TABLE beneficiaries (
    beneficiary_id       TEXT PRIMARY KEY,
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    alias                TEXT    NOT NULL,
    titular              TEXT    NOT NULL,
    tipo_destino         TEXT    NOT NULL,          -- clabe | tarjeta
    numero               TEXT    NOT NULL,          -- CLABE (18) o tarjeta (16), mock con verificador válido
    banco_codigo         TEXT    NOT NULL,
    creado_en            TEXT    NOT NULL,
    UNIQUE (client_id, numero),
    CHECK (tipo_destino IN ('clabe','tarjeta'))
);
CREATE INDEX idx_beneficiaries_client ON beneficiaries(client_id);

CREATE TABLE payments (
    payment_id           TEXT PRIMARY KEY,
    folio                TEXT    NOT NULL UNIQUE,   -- 'PG-2026-000123' (lo ve el cliente)
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    account_id           TEXT    NOT NULL REFERENCES accounts(account_id),   -- de donde sale
    tipo                 TEXT    NOT NULL,          -- servicio | transferencia | retiro_sin_tarjeta
    estado               TEXT    NOT NULL,          -- pendiente | ejecutando | ejecutada | rechazada | cancelada
    monto                REAL    NOT NULL,
    comision             REAL    NOT NULL DEFAULT 0,
    concepto             TEXT,
    -- servicio
    service_id           TEXT    REFERENCES saved_services(service_id),
    bill_id              TEXT    REFERENCES bills(bill_id),
    -- transferencia
    destino_tipo         TEXT,                      -- clabe | tarjeta | cuenta_propia
    destino_numero       TEXT,
    destino_banco        TEXT,                      -- codigo SPEI
    destino_titular      TEXT,
    destino_account_id   TEXT    REFERENCES accounts(account_id),  -- solo si el destino es de este banco
    beneficiary_id       TEXT    REFERENCES beneficiaries(beneficiary_id),
    clave_rastreo        TEXT,
    -- retiro sin tarjeta: el codigo se entrega una vez y aqui solo queda su hash
    codigo_retiro_hash   TEXT,
    codigo_vence_en      TEXT,
    -- ciclo de vida
    creada_en            TEXT    NOT NULL,
    ejecutada_en         TEXT,
    motivo_rechazo       TEXT,
    idempotency_key      TEXT    NOT NULL,
    confirmation_token_hash TEXT NOT NULL,
    CHECK (tipo IN ('servicio','transferencia','retiro_sin_tarjeta')),
    CHECK (estado IN ('pendiente','ejecutando','ejecutada','rechazada','cancelada')),
    CHECK (destino_tipo IS NULL OR destino_tipo IN ('clabe','tarjeta','cuenta_propia')),
    CHECK (monto > 0),
    CHECK (comision >= 0),
    UNIQUE (client_id, idempotency_key)
);
CREATE INDEX idx_payments_client ON payments(client_id, creada_en DESC);

-- Dinero que entra. El abono ya esta en `transactions`; esto guarda de quien
-- viene, para contestar "¿quien me deposito?" sin parsear descripciones.
CREATE TABLE incoming_transfers (
    txn_id               TEXT PRIMARY KEY REFERENCES transactions(txn_id),
    canal                TEXT    NOT NULL,          -- spei | interna | deposito_efectivo
    remitente            TEXT    NOT NULL,
    banco_origen         TEXT,                      -- codigo SPEI
    cuenta_origen_mask   TEXT,
    concepto             TEXT,
    clave_rastreo        TEXT,
    CHECK (canal IN ('spei','interna','deposito_efectivo'))
);

-- Referencias para depositar efectivo en un corresponsal (OXXO, 7-Eleven...).
-- Crear una no mueve dinero; el abono llega cuando el corresponsal liquida,
-- y eso NO es una tool del agente (ver scripts/simular_deposito.py).
CREATE TABLE deposit_references (
    reference_id         TEXT PRIMARY KEY,
    client_id            TEXT    NOT NULL REFERENCES clients(client_id),
    account_id           TEXT    NOT NULL REFERENCES accounts(account_id),
    canal_id             TEXT    NOT NULL,
    referencia           TEXT    NOT NULL UNIQUE,
    comision             REAL    NOT NULL,
    monto_maximo         REAL    NOT NULL,
    estado               TEXT    NOT NULL DEFAULT 'vigente',   -- vigente | liquidada | cancelada
    creada_en            TEXT    NOT NULL,
    vence_en             TEXT    NOT NULL,
    liquidada_en         TEXT,
    monto_liquidado      REAL,
    txn_id               TEXT    REFERENCES transactions(txn_id),
    CHECK (estado IN ('vigente','liquidada','cancelada'))
);
CREATE INDEX idx_deposit_refs_client ON deposit_references(client_id, estado);

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
    fecha_mercado        TEXT    NOT NULL,          -- fecha de la foto de mercado
    tasa_libre_riesgo    REAL    NOT NULL,          -- CETES 28d
    tasa_referencia      REAL    NOT NULL,          -- objetivo de Banxico
    tasa_larga           REAL    NOT NULL,          -- nivel de reversion de la tasa corta
    inflacion_anual      REAL    NOT NULL,
    ipc_nivel            REAL    NOT NULL,
    volatilidad_mercado  REAL    NOT NULL,
    prima_riesgo_mercado REAL    NOT NULL,
    isr_retencion_capital REAL   NOT NULL,
    isr_ganancia_capital REAL    NOT NULL,
    isr_dividendos       REAL    NOT NULL,
    seed                 INTEGER NOT NULL
);

-- Procedencia de cada parametro de mercado: anclado (observado, con fecha) o
-- estimado. Es lo que permite responder "de donde salio este numero".
CREATE TABLE market_sources (
    clave                TEXT PRIMARY KEY,
    valor                REAL    NOT NULL,
    tipo                 TEXT    NOT NULL,          -- anclado | estimado
    fuente               TEXT    NOT NULL,
    tomado_en            TEXT    NOT NULL,
    CHECK (tipo IN ('anclado','estimado'))
);
