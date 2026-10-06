-- CVP Contable — ajustes por los advisors de Supabase.
-- 1) Las funciones auxiliares de acceso salen del esquema expuesto por la API (public → privado),
--    para que no se puedan llamar como RPC. Las políticas las siguen usando (referencia por OID).
-- 3) Índices en las claves foráneas.

create schema if not exists privado;
revoke all on schema privado from public, anon;
grant usage on schema privado to authenticated;

alter function public.es_admin()                 set schema privado;
alter function public.es_usuario_activo()        set schema privado;
alter function public.puede_ver_cliente(uuid)    set schema privado;
alter function public.cliente_de_periodo(uuid)   set schema privado;
alter function public.periodo_de_corrida(uuid)   set schema privado;

create or replace function privado.puede_ver_cliente(p_cliente uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select privado.es_admin()
      or (privado.es_usuario_activo() and (
            coalesce((select (c.valor)::text::boolean from public.configuracion c
                      where c.clave = 'asignacion_por_analista'), false) = false
         or exists (select 1 from public.analista_clientes ac
                    where ac.analista_id = (select auth.uid()) and ac.cliente_id = p_cliente)));
$$;

create or replace function public.proteger_perfil()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if (new.rol is distinct from old.rol or new.activo is distinct from old.activo)
     and not privado.es_admin() and (select auth.uid()) is not null then
    raise exception 'Solo un administrador puede cambiar el rol o el estado de un usuario';
  end if;
  return new;
end;
$$;

create or replace function public.controlar_periodo()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if old.estado = 'cerrado' and new.estado = 'abierto' and not privado.es_admin()
     and (select auth.uid()) is not null then
    raise exception 'Solo un administrador puede reabrir un período cerrado';
  end if;
  if new.estado = 'cerrado' and old.estado <> 'cerrado' then
    new.cerrado_por := (select auth.uid());
    new.cerrado_en := now();
  elsif new.estado = 'abierto' then
    new.cerrado_por := null;
    new.cerrado_en := null;
  end if;
  return new;
end;
$$;
revoke execute on function public.proteger_perfil(), public.controlar_periodo() from anon, authenticated, public;

revoke execute on all functions in schema privado from public, anon;
grant execute on all functions in schema privado to authenticated;

-- ---------------------------------------------------------------- índices de claves foráneas
create index on public.analista_clientes (cliente_id);
create index on public.archivos (cuenta_id);
create index on public.archivos (subido_por);
create index on public.clientes (creado_por);
create index on public.correcciones_caja (aceptada_por);
create index on public.corridas (creada_por);
create index on public.decisiones (corrida_id);
create index on public.decisiones (revisado_por);
create index on public.periodos (cerrado_por);
