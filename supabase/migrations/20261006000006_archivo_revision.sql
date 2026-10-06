-- Paso 2: el analista puede subir el Excel de revisión (emitido por la app y con sus decisiones)
-- como un archivo más del período; el servicio lo usa como «corrida anterior».
alter table public.archivos drop constraint archivos_tipo_check;
alter table public.archivos add constraint archivos_tipo_check
  check (tipo in ('estado_cuenta', 'libro_sistema', 'cierre_caja', 'kardex', 'revision'));
