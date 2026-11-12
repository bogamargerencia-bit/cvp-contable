-- Prueba de permisos de reglas_clasificacion y asignaciones_cuenta (migración 0010).
-- Se ejecuta en el SQL Editor de Supabase; NO deja datos (termina con una excepción que revierte todo).
-- Resultado esperado (2026-11-12):
--   inactivo ve reglas=0; inactivo crea regla=bloqueado; analista ve reglas=1; analista crea regla=1;
--   regla duplicada=bloqueado; regla a nombre de otro=bloqueado; analista edita regla=1; analista borra regla=0;
--   analista asigna=1; asigna a nombre de otro=bloqueado; asignación en período cerrado=bloqueado;
--   con asignación, no asignado ve reglas=0; no asignado crea regla=bloqueado; admin borra regla=1;
--   anon ve reglas=0
do $$
declare
  a uuid := gen_random_uuid(); b uuid := gen_random_uuid(); cli uuid; per uuid; per2 uuid; reg uuid;
  n int; r text := '';
begin
  insert into auth.users (id, email, instance_id, aud, role, raw_user_meta_data)
  values (a, 'prueba-admin@x.test', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', '{}'),
         (b, 'prueba-analista@x.test', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', '{}');
  update public.perfiles set rol = 'admin', activo = true where id = a;
  insert into public.clientes (nombre) values ('CLIENTE PRUEBA REGLAS') returning id into cli;
  insert into public.periodos (cliente_id, anio, mes) values (cli, 2026, 9) returning id into per;
  insert into public.periodos (cliente_id, anio, mes) values (cli, 2026, 8) returning id into per2;
  insert into public.reglas_clasificacion (cliente_id, patron, cuenta, clasificacion, origen, creada_por)
  values (cli, 'PAGO MOVIL', 'VENTAS', 'VENTAS', 'carga_inicial', a);

  -- analista inactivo
  perform set_config('request.jwt.claims', json_build_object('sub', b, 'role', 'authenticated')::text, true);
  set local role authenticated;
  select count(*) into n from public.reglas_clasificacion where cliente_id = cli;
  r := r || 'inactivo ve reglas=' || n || '; ';
  begin
    insert into public.reglas_clasificacion (cliente_id, patron, cuenta, clasificacion) values (cli, 'X', 'Y', 'Z');
    r := r || 'inactivo crea regla=PERMITIDO(!); ';
  exception when others then r := r || 'inactivo crea regla=bloqueado; '; end;
  reset role;

  -- analista activo (sin asignación por analista)
  perform set_config('request.jwt.claims', '', true);
  update public.perfiles set activo = true where id = b;
  perform set_config('request.jwt.claims', json_build_object('sub', b, 'role', 'authenticated')::text, true);
  set local role authenticated;
  select count(*) into n from public.reglas_clasificacion where cliente_id = cli;
  r := r || 'analista ve reglas=' || n || '; ';
  insert into public.reglas_clasificacion (cliente_id, tipo, patron, cuenta, clasificacion)
  values (cli, 'contiene', 'NOMINA', 'NOMINA', 'GASTO') returning id into reg;
  select count(*) into n from public.reglas_clasificacion where id = reg and creada_por = b;
  r := r || 'analista crea regla=' || n || '; ';
  begin
    insert into public.reglas_clasificacion (cliente_id, tipo, patron, cuenta, clasificacion)
    values (cli, 'contiene', ' nomina ', 'OTROS GASTOS', 'GASTO');
    r := r || 'regla duplicada=PERMITIDO(!); ';
  exception when others then r := r || 'regla duplicada=bloqueado; '; end;
  begin
    insert into public.reglas_clasificacion (cliente_id, patron, cuenta, clasificacion, creada_por)
    values (cli, 'OTRA', 'Y', 'Z', a);
    r := r || 'regla a nombre de otro=PERMITIDO(!); ';
  exception when others then r := r || 'regla a nombre de otro=bloqueado; '; end;
  update public.reglas_clasificacion set cuenta = 'NOMINA FIJA' where id = reg; get diagnostics n = row_count;
  r := r || 'analista edita regla=' || n || '; ';
  delete from public.reglas_clasificacion where id = reg; get diagnostics n = row_count;
  r := r || 'analista borra regla=' || n || '; ';
  insert into public.asignaciones_cuenta (periodo_id, clave, cuenta, clasificacion)
  values (per, 'BANESCO|2026-09-01|-10.00|GASTO RARO#1', 'OTROS GASTOS', 'GASTO');
  select count(*) into n from public.asignaciones_cuenta where periodo_id = per and asignada_por = b;
  r := r || 'analista asigna=' || n || '; ';
  begin
    insert into public.asignaciones_cuenta (periodo_id, clave, cuenta, clasificacion, asignada_por)
    values (per, 'K2', 'X', 'Y', a);
    r := r || 'asigna a nombre de otro=PERMITIDO(!); ';
  exception when others then r := r || 'asigna a nombre de otro=bloqueado; '; end;
  update public.periodos set estado = 'cerrado' where id = per2;
  begin
    insert into public.asignaciones_cuenta (periodo_id, clave, cuenta, clasificacion) values (per2, 'K3', 'X', 'Y');
    r := r || 'asignación en período cerrado=PERMITIDO(!); ';
  exception when others then r := r || 'asignación en período cerrado=bloqueado; '; end;
  reset role;

  -- con asignación por analista, el analista no asignado no ve ni crea
  perform set_config('request.jwt.claims', '', true);
  update public.configuracion set valor = 'true'::jsonb where clave = 'asignacion_por_analista';
  perform set_config('request.jwt.claims', json_build_object('sub', b, 'role', 'authenticated')::text, true);
  set local role authenticated;
  select count(*) into n from public.reglas_clasificacion where cliente_id = cli;
  r := r || 'con asignación, no asignado ve reglas=' || n || '; ';
  begin
    insert into public.reglas_clasificacion (cliente_id, patron, cuenta, clasificacion) values (cli, 'Z', 'Y', 'X');
    r := r || 'no asignado crea regla=PERMITIDO(!); ';
  exception when others then r := r || 'no asignado crea regla=bloqueado; '; end;
  reset role;

  -- admin
  perform set_config('request.jwt.claims', json_build_object('sub', a, 'role', 'authenticated')::text, true);
  set local role authenticated;
  delete from public.reglas_clasificacion where id = reg; get diagnostics n = row_count;
  r := r || 'admin borra regla=' || n || '; ';
  reset role;

  perform set_config('request.jwt.claims', json_build_object('role', 'anon')::text, true);
  set local role anon;
  begin
    select count(*) into n from public.reglas_clasificacion;
    r := r || 'anon ve reglas=' || n;
  exception when others then r := r || 'anon ve reglas=0 (sin permiso)'; end;
  reset role;

  raise exception 'RESULTADO: %', r;
end $$;
