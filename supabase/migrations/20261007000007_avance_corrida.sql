-- Avance de la corrida, para la barra de progreso en la web. Lo escribe el servicio (service_role).
alter table public.corridas
  add column etapa text,
  add column avance smallint not null default 0 check (avance between 0 and 100);
