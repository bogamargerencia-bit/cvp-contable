-- CVP Contable — «Clasificación por cuenta» en la app (complementa la 0010).
--
-- reglas_clasificacion:
--   - tipo 'regex' (expresión sobre la descripción en mayúsculas y sin acentos);
--   - cuenta/clasificación nulas = «revisar siempre a mano» (p. ej. DEV CREDITO INMEDIATO);
--   - prioridad: las reglas que no son 'exacta' se prueban de menor a mayor prioridad (el orden importa:
--     «PAGO MOVIL BANESCO» = traslado debe ir antes que «PAGO MOVIL» = venta). Las 'exacta' van siempre primero.
-- asignaciones_cuenta: «excluir» (fila repetida o fuera del mes) sin cuenta.
-- periodos.saldos: saldos que informa el cliente por banco/caja: {"BANESCO": {"inicial": "635917.59",
--   "final": null}}. Montos como texto (nunca number) para no perder céntimos.

alter table public.reglas_clasificacion drop constraint reglas_clasificacion_tipo_check;
alter table public.reglas_clasificacion add constraint reglas_clasificacion_tipo_check
  check (tipo in ('exacta', 'empieza', 'contiene', 'regex'));
alter table public.reglas_clasificacion alter column cuenta drop not null, alter column clasificacion drop not null;
alter table public.reglas_clasificacion add constraint reglas_clasificacion_cuenta_y_clasificacion
  check ((cuenta is null) = (clasificacion is null));
alter table public.reglas_clasificacion add column prioridad int not null default 100;

alter table public.asignaciones_cuenta alter column cuenta drop not null, alter column clasificacion drop not null;
alter table public.asignaciones_cuenta add column excluir boolean not null default false;
alter table public.asignaciones_cuenta add constraint asignaciones_cuenta_o_excluir
  check (excluir or (cuenta is not null and clasificacion is not null));

alter table public.periodos add column saldos jsonb not null default '{}'::jsonb
  check (jsonb_typeof(saldos) = 'object');
comment on column public.periodos.saldos is
  'Saldos informados por el cliente por banco/caja (modo clasificación por cuenta); montos como texto.';

-- Con el período cerrado no se cambian los saldos (el resto de periodos ya lo controlan sus triggers).
create or replace function public.controlar_saldos()
returns trigger language plpgsql set search_path = '' as $$
begin
  if old.estado = 'cerrado' and new.estado = 'cerrado' and new.saldos is distinct from old.saldos then
    raise exception 'El período está cerrado: no se pueden cambiar los saldos';
  end if;
  return new;
end;
$$;
revoke execute on function public.controlar_saldos() from anon, authenticated, public;
create trigger controlar_saldos before update of saldos on public.periodos
  for each row execute function public.controlar_saldos();
