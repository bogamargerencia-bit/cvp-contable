-- Prueba de permisos (RLS + triggers). Se ejecuta en el SQL Editor de Supabase; NO deja datos:
-- todo ocurre dentro de un bloque que termina con una excepción (se revierte la transacción).
-- Resultado esperado (2026-10-06):
--   perfiles auto inactivos=2; inactivo ve clientes=0; autoactivarse=bloqueado; analista activo ve clientes=1;
--   analista crea cliente=bloqueado; analista se hace admin=bloqueado; analista cambia a otro filas=0;
--   analista reabre=bloqueado; analista ve auditoria=0; con asignación, no asignado ve=0;
--   admin ve clientes=1; admin reabre=1; admin ve auditoria=9; anon ve clientes=0
do $$
declare
  a uuid := gen_random_uuid(); b uuid := gen_random_uuid(); cli uuid; n int; r text := '';
begin
  insert into auth.users (id, email, instance_id, aud, role, raw_user_meta_data)
  values (a, 'prueba-admin@x.test', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', '{"nombre":"Admin Prueba"}'),
         (b, 'prueba-analista@x.test', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', '{}');
  select count(*) into n from public.perfiles where id in (a,b) and not activo and rol='analista';
  r := r || 'perfiles auto inactivos=' || n || '; ';
  update public.perfiles set rol='admin', activo=true where id=a;
  insert into public.clientes (nombre) values ('CLIENTE PRUEBA') returning id into cli;

  perform set_config('request.jwt.claims', json_build_object('sub', b, 'role','authenticated')::text, true);
  set local role authenticated;
  select count(*) into n from public.clientes; r := r || 'inactivo ve clientes=' || n || '; ';
  begin update public.perfiles set activo=true where id=b; r := r || 'autoactivarse=PERMITIDO(!); ';
  exception when others then r := r || 'autoactivarse=bloqueado; '; end;
  reset role;

  perform set_config('request.jwt.claims', '', true);
  update public.perfiles set activo=true where id=b;
  perform set_config('request.jwt.claims', json_build_object('sub', b, 'role','authenticated')::text, true);
  set local role authenticated;
  select count(*) into n from public.clientes; r := r || 'analista activo ve clientes=' || n || '; ';
  begin insert into public.clientes (nombre) values ('X'); r := r || 'analista crea cliente=PERMITIDO(!); ';
  exception when others then r := r || 'analista crea cliente=bloqueado; '; end;
  begin update public.perfiles set rol='admin' where id=b; r := r || 'analista se hace admin=PERMITIDO(!); ';
  exception when others then r := r || 'analista se hace admin=bloqueado; '; end;
  update public.perfiles set rol='analista' where id=a; get diagnostics n = row_count;
  r := r || 'analista cambia a otro filas=' || n || '; ';
  insert into public.periodos (cliente_id, anio, mes) values (cli, 2026, 9);
  update public.periodos set estado='cerrado' where cliente_id=cli;
  begin update public.periodos set estado='abierto' where cliente_id=cli; r := r || 'analista reabre=PERMITIDO(!); ';
  exception when others then r := r || 'analista reabre=bloqueado; '; end;
  select count(*) into n from public.auditoria; r := r || 'analista ve auditoria=' || n || '; ';
  reset role;

  perform set_config('request.jwt.claims', '', true);
  update public.configuracion set valor='true' where clave='asignacion_por_analista';
  perform set_config('request.jwt.claims', json_build_object('sub', b, 'role','authenticated')::text, true);
  set local role authenticated;
  select count(*) into n from public.clientes; r := r || 'con asignación, no asignado ve=' || n || '; ';
  reset role;

  perform set_config('request.jwt.claims', json_build_object('sub', a, 'role','authenticated')::text, true);
  set local role authenticated;
  select count(*) into n from public.clientes; r := r || 'admin ve clientes=' || n || '; ';
  update public.periodos set estado='abierto' where cliente_id=cli;
  select count(*) into n from public.periodos where cliente_id=cli and estado='abierto'; r := r || 'admin reabre=' || n || '; ';
  select count(*) into n from public.auditoria; r := r || 'admin ve auditoria=' || n || '; ';
  reset role;

  perform set_config('request.jwt.claims', '', true);
  set local role anon;
  begin select count(*) into n from public.clientes; r := r || 'anon ve clientes=' || n || '; ';
  exception when others then r := r || 'anon=sin permiso; '; end;
  reset role;
  raise exception 'RESULTADO: %', r;
end $$;
