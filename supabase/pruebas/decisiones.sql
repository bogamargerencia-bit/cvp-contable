-- Prueba de registrar_decision (paso 3). Se ejecuta en el SQL Editor; NO deja datos (termina con excepción).
-- Usa la última corrida «lista» que exista. Resultado esperado (2026-10-07):
--   inactivo=bloqueado; activo decide=1 vigente; cambia=1 vigente/2 total; justificado sin comentario=bloqueado;
--   código inexistente=bloqueado; período cerrado=bloqueado; anon=sin permiso
do $$
declare
  u uuid := gen_random_uuid(); cor uuid; per uuid; cod text; n int; m int; r text := '';
begin
  select c.id, c.periodo_id, pa.codigo into cor, per, cod
    from public.corridas c join public.partidas pa on pa.corrida_id = c.id
   where c.estado = 'lista' order by c.creada_en desc limit 1;
  if cor is null then raise exception 'No hay corridas listas para probar'; end if;
  update public.periodos set estado = 'abierto' where id = per;
  insert into auth.users (id, email, instance_id, aud, role, raw_user_meta_data)
  values (u, 'prueba-dec@x.test', '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', '{}');

  perform set_config('request.jwt.claims', json_build_object('sub', u, 'role', 'authenticated')::text, true);
  set local role authenticated;
  begin perform public.registrar_decision(cor, cod, 'Aceptar', null); r := r || 'inactivo=PERMITIDO(!); ';
  exception when others then r := r || 'inactivo=bloqueado; '; end;
  reset role;

  perform set_config('request.jwt.claims', '', true);
  update public.perfiles set activo = true where id = u;
  perform set_config('request.jwt.claims', json_build_object('sub', u, 'role', 'authenticated')::text, true);
  set local role authenticated;
  perform public.registrar_decision(cor, cod, 'Aceptar', '  ');
  select count(*) into n from public.decisiones where periodo_id = per and codigo = cod and vigente and revisado_por = u;
  r := r || 'activo decide=' || n || ' vigente; ';
  perform public.registrar_decision(cor, cod, 'Justificado', 'Verificado');
  select count(*) filter (where vigente), count(*) filter (where revisado_por = u) into n, m
    from public.decisiones where periodo_id = per and codigo = cod;
  r := r || 'cambia=' || n || ' vigente/' || m || ' total; ';
  begin perform public.registrar_decision(cor, cod, 'Justificado', ''); r := r || 'justificado sin comentario=PERMITIDO(!); ';
  exception when others then r := r || 'justificado sin comentario=bloqueado; '; end;
  begin perform public.registrar_decision(cor, 'NO-EXISTE', 'Aceptar', null); r := r || 'código inexistente=PERMITIDO(!); ';
  exception when others then r := r || 'código inexistente=bloqueado; '; end;
  update public.periodos set estado = 'cerrado' where id = per;
  begin perform public.registrar_decision(cor, cod, 'Aceptar', null); r := r || 'período cerrado=PERMITIDO(!); ';
  exception when others then r := r || 'período cerrado=bloqueado; '; end;
  reset role;

  perform set_config('request.jwt.claims', '', true);
  set local role anon;
  begin perform public.registrar_decision(cor, cod, 'Aceptar', null); r := r || 'anon=PERMITIDO(!); ';
  exception when others then r := r || 'anon=sin permiso; '; end;
  reset role;
  raise exception 'RESULTADO: %', r;
end $$;
