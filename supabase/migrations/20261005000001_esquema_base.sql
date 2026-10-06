-- CVP Contable — esquema base (Fase 2, paso 1)
-- Montos SIEMPRE numeric(18,2); tasas numeric(18,6). Nada de float.
-- RLS en todas las tablas. La clave service_role solo vive en el servidor (web y servicio Python).

-- ---------------------------------------------------------------- perfiles y roles
create table public.perfiles (
  id          uuid primary key references auth.users (id) on delete cascade,
  email       text not null,
  nombre      text,
  rol         text not null default 'analista' check (rol in ('admin', 'analista')),
  activo      boolean not null default true,
  creado_en   timestamptz not null default now()
);
comment on table public.perfiles is 'Usuarios internos de CVP. Rol admin o analista. Los clientes NO tienen acceso.';

-- Configuración global (p. ej. si los analistas solo ven los clientes asignados).
create table public.configuracion (
  clave       text primary key,
  valor       jsonb not null,
  actualizado_en timestamptz not null default now()
);
insert into public.configuracion (clave, valor) values ('asignacion_por_analista', 'false'::jsonb);

-- ---------------------------------------------------------------- clientes y cuentas
create table public.clientes (
  id                uuid primary key default gen_random_uuid(),
  nombre            text not null,                    -- razón social
  nombre_comercial  text,                             -- p. ej. WEI REST
  rif               text,
  clave_config      text,                             -- clave en parser/cvp_parser/clientes.py (WEI REST, CACAO)
  config            jsonb not null default '{}'::jsonb,  -- en el futuro: medios de caja, asientos resumen, divisas
  activo            boolean not null default true,
  creado_en         timestamptz not null default now(),
  creado_por        uuid references public.perfiles (id)
);
create unique index clientes_rif_unico on public.clientes (rif) where rif is not null;

-- Asignación de clientes por analista: preparada; solo se aplica si configuracion.asignacion_por_analista = true.
create table public.analista_clientes (
  analista_id uuid not null references public.perfiles (id) on delete cascade,
  cliente_id  uuid not null references public.clientes (id) on delete cascade,
  primary key (analista_id, cliente_id)
);

create table public.cuentas (
  id          uuid primary key default gen_random_uuid(),
  cliente_id  uuid not null references public.clientes (id) on delete cascade,
  tipo        text not null check (tipo in ('banco', 'divisa')),
  banco       text,                 -- código del lector: BNC, BANPLUS, 100_BANCO, PLAZA, ACTIVO, MERCANTIL…
  nombre      text not null,        -- «BNC ***1800», «Zelle», «Efectivo $»
  numero      text,
  titular     text,
  es_personal boolean not null default false,   -- cuenta de un socio usada para la empresa
  moneda      text not null default 'VES' check (moneda in ('VES', 'USD')),
  activo      boolean not null default true,
  creado_en   timestamptz not null default now()
);
create index on public.cuentas (cliente_id);

-- ---------------------------------------------------------------- períodos, archivos, corridas
create table public.periodos (
  id          uuid primary key default gen_random_uuid(),
  cliente_id  uuid not null references public.clientes (id) on delete cascade,
  anio        int  not null check (anio between 2020 and 2100),
  mes         int  not null check (mes between 1 and 12),
  estado      text not null default 'abierto' check (estado in ('abierto', 'cerrado')),
  cerrado_por uuid references public.perfiles (id),
  cerrado_en  timestamptz,
  creado_en   timestamptz not null default now(),
  unique (cliente_id, anio, mes)
);

create table public.archivos (
  id              uuid primary key default gen_random_uuid(),
  periodo_id      uuid not null references public.periodos (id) on delete cascade,
  cuenta_id       uuid references public.cuentas (id),
  tipo            text not null check (tipo in ('estado_cuenta', 'libro_sistema', 'cierre_caja', 'kardex')),
  storage_path    text not null unique,      -- {cliente_id}/{periodo_id}/{uuid}-{nombre}
  nombre_original text not null,
  sha256          text not null,
  tamano          bigint not null,
  vigente         boolean not null default true,   -- al subir una versión nueva, la anterior deja de ser vigente
  subido_por      uuid references public.perfiles (id),
  subido_en       timestamptz not null default now()
);
create index on public.archivos (periodo_id) where vigente;

create table public.corridas (
  id          uuid primary key default gen_random_uuid(),
  periodo_id  uuid not null references public.periodos (id) on delete cascade,
  numero      int  not null,
  estado      text not null default 'pendiente' check (estado in ('pendiente', 'procesando', 'lista', 'error')),
  ok_general  boolean,
  resumen     jsonb,                  -- cuadres, conteos por estado, alertas
  excel_path  text,                   -- Excel generado (Storage)
  error       text,
  archivos    uuid[] not null default '{}',   -- archivos usados en esta corrida
  creada_por  uuid references public.perfiles (id),
  creada_en   timestamptz not null default now(),
  terminada_en timestamptz,
  unique (periodo_id, numero)
);

-- ---------------------------------------------------------------- revisión
-- Partidas que emite cada corrida (código estable entre corridas; ver parser/cvp_parser/revision.py).
create table public.partidas (
  id          uuid primary key default gen_random_uuid(),
  corrida_id  uuid not null references public.corridas (id) on delete cascade,
  codigo      text not null,
  banco       text,
  origen      text not null,
  tipo        text not null,
  fecha       date,
  descripcion text,
  monto_bs    numeric(18,2),
  monto_usd   numeric(18,2),
  detalle     text,
  sugerencia  text,
  situacion   text not null,          -- Nuevo / Sin decisión / Cerrado / Marcado como corregido… / Decisión incompleta
  aviso       text,
  propuesta   jsonb,                  -- corrección de fecha de caja propuesta: {"fila": 30, "fecha": "2026-08-26"}
  unique (corrida_id, codigo)
);

-- Decisiones del analista por período y código. Se arrastran a las corridas siguientes.
create table public.decisiones (
  id            uuid primary key default gen_random_uuid(),
  periodo_id    uuid not null references public.periodos (id) on delete cascade,
  codigo        text not null,
  decision      text not null check (decision in ('Aceptar', 'Justificado', 'Corregido en el sistema')),
  comentario    text,
  revisado_por  uuid not null references public.perfiles (id),
  decidido_en   timestamptz not null default now(),
  corrida_id    uuid references public.corridas (id),   -- corrida en la que se decidió
  vigente       boolean not null default true,
  constraint justificado_con_comentario check (decision <> 'Justificado' or coalesce(trim(comentario), '') <> '')
);
create unique index decisiones_vigente_unica on public.decisiones (periodo_id, codigo) where vigente;

-- Correcciones de fecha del cierre de caja aceptadas (se aplican al leer; el archivo no se toca).
create table public.correcciones_caja (
  id           uuid primary key default gen_random_uuid(),
  periodo_id   uuid not null references public.periodos (id) on delete cascade,
  codigo       text not null,
  fila         int  not null,
  fecha_actual date not null,
  fecha_nueva  date not null,
  aceptada_por uuid not null references public.perfiles (id),
  aceptada_en  timestamptz not null default now(),
  unique (periodo_id, fila)
);

-- ---------------------------------------------------------------- auditoría
create table public.auditoria (
  id          bigint generated always as identity primary key,
  usuario_id  uuid,
  accion      text not null,          -- INSERT / UPDATE / DELETE
  tabla       text not null,
  registro_id text,
  antes       jsonb,
  despues     jsonb,
  creado_en   timestamptz not null default now()
);
create index on public.auditoria (tabla, registro_id);
create index on public.auditoria (creado_en desc);
