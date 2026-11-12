-- CVP Contable — modo «Clasificación por cuenta» (Delicateses): reglas por cliente y asignaciones del mes.
--
-- reglas_clasificacion: «si la descripción es / empieza por / contiene X → CUENTA, CLASIFICACIÓN»,
--   opcionalmente solo para un banco o un sentido (ingreso / egreso). Los analistas que ven al cliente las
--   crean, editan y desactivan; borrar solo un admin (lo normal es desactivar, para conservar el historial).
-- asignaciones_cuenta: la cuenta que el analista eligió a mano para un movimiento POR CLASIFICAR de un
--   período. La clave identifica el movimiento aunque el archivo se vuelva a subir
--   (banco|fecha|monto|descripción#ocurrencia, ver claves() en parser/cvp_parser/clasificacion_cuentas.py).
-- Los nombres de proveedores y personas viven aquí (con RLS), no en el código: el repositorio es público.

create table public.reglas_clasificacion (
  id             uuid primary key default gen_random_uuid(),
  cliente_id     uuid not null references public.clientes (id) on delete cascade,
  tipo           text not null default 'exacta' check (tipo in ('exacta', 'empieza', 'contiene')),
  patron         text not null check (length(btrim(patron)) > 0),
  cuenta         text not null check (length(btrim(cuenta)) > 0),
  clasificacion  text not null check (length(btrim(clasificacion)) > 0),
  banco          text,
  sentido        text check (sentido in ('ingreso', 'egreso')),
  activa         boolean not null default true,
  origen         text not null default 'manual' check (origen in ('manual', 'carga_inicial', 'decision')),
  nota           text,
  creada_por     uuid references public.perfiles (id) default auth.uid(),
  creada_en      timestamptz not null default now(),
  actualizada_en timestamptz
);
comment on table public.reglas_clasificacion is
  'Reglas descripción → cuenta contable por cliente (modo clasificación por cuenta).';
create index on public.reglas_clasificacion (cliente_id) where activa;
create index on public.reglas_clasificacion (creada_por);
-- Una sola regla activa por patrón (sin distinguir mayúsculas), tipo, banco y sentido.
create unique index reglas_clasificacion_unica on public.reglas_clasificacion
  (cliente_id, tipo, upper(btrim(patron)), coalesce(upper(banco), ''), coalesce(sentido, '')) where activa;

create table public.asignaciones_cuenta (
  id             uuid primary key default gen_random_uuid(),
  periodo_id     uuid not null references public.periodos (id) on delete cascade,
  clave          text not null,
  cuenta         text not null check (length(btrim(cuenta)) > 0),
  clasificacion  text not null check (length(btrim(clasificacion)) > 0),
  regla_id       uuid references public.reglas_clasificacion (id) on delete set null,  -- si se «recordó»
  asignada_por   uuid not null references public.perfiles (id) default auth.uid(),
  asignada_en    timestamptz not null default now(),
  unique (periodo_id, clave)
);
create index on public.asignaciones_cuenta (asignada_por);
create index on public.asignaciones_cuenta (regla_id);

alter table public.archivos drop constraint archivos_tipo_check;
alter table public.archivos add constraint archivos_tipo_check
  check (tipo in ('estado_cuenta', 'libro_sistema', 'cierre_caja', 'kardex', 'revision', 'movimientos_cliente'));

create or replace function public.tocar_regla()
returns trigger language plpgsql set search_path = '' as $$
begin
  new.actualizada_en := now();
  return new;
end;
$$;
revoke execute on function public.tocar_regla() from anon, authenticated, public;
create trigger tocar_regla before update on public.reglas_clasificacion
  for each row execute function public.tocar_regla();

-- Las asignaciones de un período cerrado no se cambian.
create or replace function public.controlar_asignacion()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if exists (select 1 from public.periodos p where p.id = coalesce(new.periodo_id, old.periodo_id)
             and p.estado = 'cerrado') then
    raise exception 'El período está cerrado: no se pueden cambiar las asignaciones';
  end if;
  return coalesce(new, old);
end;
$$;
revoke execute on function public.controlar_asignacion() from anon, authenticated, public;
create trigger controlar_asignacion before insert or update or delete on public.asignaciones_cuenta
  for each row execute function public.controlar_asignacion();

create trigger auditar after insert or update or delete on public.reglas_clasificacion
  for each row execute function public.auditar();
create trigger auditar after insert or update or delete on public.asignaciones_cuenta
  for each row execute function public.auditar();

alter table public.reglas_clasificacion enable row level security;
alter table public.asignaciones_cuenta  enable row level security;

create policy reglas_select on public.reglas_clasificacion for select to authenticated
  using (privado.puede_ver_cliente(cliente_id));
create policy reglas_insert on public.reglas_clasificacion for insert to authenticated
  with check (privado.puede_ver_cliente(cliente_id) and creada_por = (select auth.uid()));
create policy reglas_update on public.reglas_clasificacion for update to authenticated
  using (privado.puede_ver_cliente(cliente_id)) with check (privado.puede_ver_cliente(cliente_id));
create policy reglas_delete on public.reglas_clasificacion for delete to authenticated
  using (privado.es_admin());

create policy asignaciones_select on public.asignaciones_cuenta for select to authenticated
  using (privado.puede_ver_cliente(privado.cliente_de_periodo(periodo_id)));
create policy asignaciones_insert on public.asignaciones_cuenta for insert to authenticated
  with check (privado.puede_ver_cliente(privado.cliente_de_periodo(periodo_id))
              and asignada_por = (select auth.uid()));
create policy asignaciones_update on public.asignaciones_cuenta for update to authenticated
  using (privado.puede_ver_cliente(privado.cliente_de_periodo(periodo_id)))
  with check (privado.puede_ver_cliente(privado.cliente_de_periodo(periodo_id))
              and asignada_por = (select auth.uid()));
create policy asignaciones_delete on public.asignaciones_cuenta for delete to authenticated
  using (privado.puede_ver_cliente(privado.cliente_de_periodo(periodo_id)));

grant select, insert, update, delete on public.reglas_clasificacion, public.asignaciones_cuenta to authenticated;
