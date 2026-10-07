-- Revisión en línea (paso 3): registrar la decisión de una partida desde la web.
-- security invoker: corre con los permisos del usuario, así que aplican las mismas políticas RLS
-- (debe tener acceso al cliente y firma con su propio id). En una sola transacción:
-- la decisión anterior del mismo código deja de ser vigente (queda para el historial) y se inserta la nueva.
create or replace function public.registrar_decision(
  p_corrida uuid, p_codigo text, p_decision text, p_comentario text
) returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_periodo uuid;
begin
  select c.periodo_id into v_periodo
  from public.corridas c
  join public.partidas pa on pa.corrida_id = c.id and pa.codigo = p_codigo
  where c.id = p_corrida and c.estado = 'lista';
  if v_periodo is null then
    raise exception 'La partida % no existe en esa corrida', p_codigo using errcode = 'P0002';
  end if;
  if exists (select 1 from public.periodos where id = v_periodo and estado = 'cerrado') then
    raise exception 'El período está cerrado' using errcode = 'P0001';
  end if;
  update public.decisiones set vigente = false
   where periodo_id = v_periodo and codigo = p_codigo and vigente;
  insert into public.decisiones (periodo_id, codigo, decision, comentario, revisado_por, corrida_id)
  values (v_periodo, p_codigo, p_decision, nullif(trim(p_comentario), ''), (select auth.uid()), p_corrida);
end $$;

revoke execute on function public.registrar_decision(uuid, text, text, text) from public, anon;
grant execute on function public.registrar_decision(uuid, text, text, text) to authenticated;
