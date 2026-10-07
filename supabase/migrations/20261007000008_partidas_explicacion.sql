-- Diagnóstico automático: cada partida trae qué pasó y qué hacer, en lenguaje claro (parser/cvp_parser/diagnostico.py).
-- Columnas nuevas, sin cambio de políticas: partidas ya tiene RLS (lectura por puede_ver_cliente, escritura solo service_role).
alter table public.partidas
  add column explicacion text,
  add column que_hacer   text;
