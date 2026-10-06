-- CVP Contable — funciones de acceso, RLS, auditoría y storage.

-- ---------------------------------------------------------------- funciones de acceso
create or replace function public.es_admin()
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.perfiles p
                 where p.id = (select auth.uid()) and p.rol = 'admin' and p.activo);
$$;

create or replace function public.es_usuario_activo()
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.perfiles p where p.id = (select auth.uid()) and p.activo);
$$;

-- Todos los analistas activos ven todos los clientes, salvo que se active la asignación por analista.
create or replace function public.puede_ver_cliente(p_cliente uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select public.es_admin()
      or (public.es_usuario_activo() and (
            coalesce((select (c.valor)::text::boolean from public.configuracion c
                      where c.clave = 'asignacion_por_analista'), false) = false
         or exists (select 1 from public.analista_clientes ac
                    where ac.analista_id = (select auth.uid()) and ac.cliente_id = p_cliente)));
$$;

create or replace function public.cliente_de_periodo(p_periodo uuid)
returns uuid language sql stable security definer set search_path = '' as $$
  select cliente_id from public.periodos where id = p_periodo;
$$;

create or replace function public.periodo_de_corrida(p_corrida uuid)
returns uuid language sql stable security definer set search_path = '' as $$
  select periodo_id from public.corridas where id = p_corrida;
$$;

-- ---------------------------------------------------------------- perfil al registrarse
create or replace function public.crear_perfil()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.perfiles (id, email, nombre)
  values (new.id, new.email, coalesce(new.raw_user_meta_data ->> 'nombre', split_part(new.email, '@', 1)));
  return new;
end;
$$;
create trigger al_crear_usuario after insert on auth.users
  for each row execute function public.crear_perfil();

-- Un usuario no puede cambiarse el rol ni activarse a sí mismo (solo un admin).
create or replace function public.proteger_perfil()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if (new.rol is distinct from old.rol or new.activo is distinct from old.activo)
     and not public.es_admin() and (select auth.uid()) is not null then
    raise exception 'Solo un administrador puede cambiar el rol o el estado de un usuario';
  end if;
  return new;
end;
$$;
create trigger proteger_perfil before update on public.perfiles
  for each row execute function public.proteger_perfil();

-- Reabrir un período cerrado: solo admin. Cerrar: cualquier usuario con acceso (lo da el analista).
create or replace function public.controlar_periodo()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if old.estado = 'cerrado' and new.estado = 'abierto' and not public.es_admin()
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
create trigger controlar_periodo before update on public.periodos
  for each row execute function public.controlar_periodo();

-- ---------------------------------------------------------------- auditoría genérica
create or replace function public.auditar()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.auditoria (usuario_id, accion, tabla, registro_id, antes, despues)
  values ((select auth.uid()), tg_op, tg_table_name,
          coalesce((case when tg_op = 'DELETE' then to_jsonb(old) else to_jsonb(new) end) ->> 'id', ''),
          case when tg_op in ('UPDATE', 'DELETE') then to_jsonb(old) end,
          case when tg_op in ('INSERT', 'UPDATE') then to_jsonb(new) end);
  return coalesce(new, old);
end;
$$;

do $$
declare t text;
begin
  foreach t in array array['perfiles', 'configuracion', 'clientes', 'analista_clientes', 'cuentas', 'periodos',
                           'archivos', 'corridas', 'decisiones', 'correcciones_caja']
  loop
    execute format('create trigger auditar after insert or update or delete on public.%I
                    for each row execute function public.auditar()', t);
  end loop;
end $$;

-- ---------------------------------------------------------------- RLS
alter table public.perfiles          enable row level security;
alter table public.configuracion     enable row level security;
alter table public.clientes          enable row level security;
alter table public.analista_clientes enable row level security;
alter table public.cuentas           enable row level security;
alter table public.periodos          enable row level security;
alter table public.archivos          enable row level security;
alter table public.corridas          enable row level security;
alter table public.partidas          enable row level security;
alter table public.decisiones        enable row level security;
alter table public.correcciones_caja enable row level security;
alter table public.auditoria         enable row level security;

-- perfiles: cada uno ve el suyo; el admin ve y edita todos.
create policy perfiles_select on public.perfiles for select to authenticated
  using (id = (select auth.uid()) or public.es_admin() or public.es_usuario_activo());
create policy perfiles_update_admin on public.perfiles for update to authenticated
  using (public.es_admin()) with check (public.es_admin());
create policy perfiles_update_propio on public.perfiles for update to authenticated
  using (id = (select auth.uid())) with check (id = (select auth.uid()));

-- configuración y asignaciones: lectura para usuarios activos, escritura solo admin.
create policy configuracion_select on public.configuracion for select to authenticated using (public.es_usuario_activo());
create policy configuracion_admin on public.configuracion for all to authenticated
  using (public.es_admin()) with check (public.es_admin());
create policy asignaciones_select on public.analista_clientes for select to authenticated
  using (public.es_admin() or analista_id = (select auth.uid()));
create policy asignaciones_admin on public.analista_clientes for all to authenticated
  using (public.es_admin()) with check (public.es_admin());

-- clientes y cuentas: ver según acceso; crear/editar solo admin.
create policy clientes_select on public.clientes for select to authenticated using (public.puede_ver_cliente(id));
create policy clientes_admin on public.clientes for all to authenticated
  using (public.es_admin()) with check (public.es_admin());
create policy cuentas_select on public.cuentas for select to authenticated using (public.puede_ver_cliente(cliente_id));
create policy cuentas_admin on public.cuentas for all to authenticated
  using (public.es_admin()) with check (public.es_admin());

-- períodos: ver/crear/actualizar (cerrar) con acceso al cliente; borrar solo admin.
create policy periodos_select on public.periodos for select to authenticated using (public.puede_ver_cliente(cliente_id));
create policy periodos_insert on public.periodos for insert to authenticated with check (public.puede_ver_cliente(cliente_id));
create policy periodos_update on public.periodos for update to authenticated
  using (public.puede_ver_cliente(cliente_id)) with check (public.puede_ver_cliente(cliente_id));
create policy periodos_delete on public.periodos for delete to authenticated using (public.es_admin());

-- archivos: ver y subir con acceso al cliente del período; nunca se borran desde la web (se marcan no vigentes).
create policy archivos_select on public.archivos for select to authenticated
  using (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)));
create policy archivos_insert on public.archivos for insert to authenticated
  with check (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)) and subido_por = (select auth.uid()));
create policy archivos_update on public.archivos for update to authenticated
  using (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)))
  with check (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)));

-- corridas: ver y crear (pedir procesamiento) con acceso; el servicio Python las actualiza con service_role.
create policy corridas_select on public.corridas for select to authenticated
  using (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)));
create policy corridas_insert on public.corridas for insert to authenticated
  with check (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)) and creada_por = (select auth.uid()));

-- partidas: solo lectura para usuarios (las escribe el servicio Python).
create policy partidas_select on public.partidas for select to authenticated
  using (public.puede_ver_cliente(public.cliente_de_periodo(public.periodo_de_corrida(corrida_id))));

-- decisiones y correcciones: ver y registrar con acceso; cada uno firma lo suyo.
create policy decisiones_select on public.decisiones for select to authenticated
  using (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)));
create policy decisiones_insert on public.decisiones for insert to authenticated
  with check (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)) and revisado_por = (select auth.uid()));
create policy decisiones_update on public.decisiones for update to authenticated
  using (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)))
  with check (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)));
create policy correcciones_select on public.correcciones_caja for select to authenticated
  using (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)));
create policy correcciones_insert on public.correcciones_caja for insert to authenticated
  with check (public.puede_ver_cliente(public.cliente_de_periodo(periodo_id)) and aceptada_por = (select auth.uid()));

-- auditoría: solo el admin la lee; se escribe por trigger.
create policy auditoria_select on public.auditoria for select to authenticated using (public.es_admin());

-- Las funciones auxiliares no se exponen como RPC a anónimos.
revoke execute on function public.es_admin(), public.es_usuario_activo(), public.puede_ver_cliente(uuid),
  public.cliente_de_periodo(uuid), public.periodo_de_corrida(uuid) from anon, public;
grant execute on function public.es_admin(), public.es_usuario_activo(), public.puede_ver_cliente(uuid),
  public.cliente_de_periodo(uuid), public.periodo_de_corrida(uuid) to authenticated;
revoke execute on function public.crear_perfil(), public.proteger_perfil(), public.controlar_periodo(),
  public.auditar() from anon, authenticated, public;

-- ---------------------------------------------------------------- storage privado
insert into storage.buckets (id, name, public, file_size_limit)
values ('archivos', 'archivos', false, 52428800)
on conflict (id) do nothing;

-- Ruta: {cliente_id}/{periodo_id}/{archivo}. Ver/subir según acceso al cliente; borrar solo admin.
create policy archivos_storage_select on storage.objects for select to authenticated
  using (bucket_id = 'archivos' and public.puede_ver_cliente(((storage.foldername(name))[1])::uuid));
create policy archivos_storage_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'archivos' and public.puede_ver_cliente(((storage.foldername(name))[1])::uuid));
create policy archivos_storage_delete on storage.objects for delete to authenticated
  using (bucket_id = 'archivos' and public.es_admin());
