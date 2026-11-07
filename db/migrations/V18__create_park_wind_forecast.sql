-- Migration: hourly 7-day wind forecast per park, refreshed by `smarthack.jobs.wind_forecast_job`.
--
-- The table is a snapshot, not a history: every refresh replaces all of its rows. The
-- replacement goes through `replace_park_wind_forecast`, so the delete and the insert share
-- one transaction and a reader never sees the table empty or half-written.
--
-- Columns mirror the Open-Meteo variables the wind power model (`smarthack/wind`) is fed,
-- in SI units: speeds in m/s, directions in degrees, temperatures in degrees Celsius.

create table if not exists public.park_wind_forecast (
    park_id              bigint      not null,
    forecast_time        timestamptz not null,
    wind_speed_10m       real,
    wind_speed_100m      real,
    wind_direction_10m   real,
    wind_direction_100m  real,
    wind_gusts_10m       real,
    temperature_2m       real,
    relative_humidity_2m real,
    dew_point_2m         real,
    surface_pressure     real,
    fetched_at           timestamptz not null default now(),
    constraint park_wind_forecast_pk primary key (park_id, forecast_time),
    constraint park_wind_forecast_park_fk
        foreign key (park_id) references public.park(id) on delete cascade
);

comment on table public.park_wind_forecast is
    'Hourly wind forecast for the next 7 days per park (Open-Meteo). Fully replaced on every refresh.';
comment on column public.park_wind_forecast.forecast_time is 'Start of the forecast hour, UTC.';
comment on column public.park_wind_forecast.wind_speed_100m is 'm/s, close to hub height.';
comment on column public.park_wind_forecast.temperature_2m is 'Degrees Celsius.';
comment on column public.park_wind_forecast.surface_pressure is 'hPa.';
comment on column public.park_wind_forecast.fetched_at is 'When the refresh that wrote this row ran.';

-- Atomic full overwrite. `rows` is a JSON array of objects keyed by the column names above.
create or replace function public.replace_park_wind_forecast(rows jsonb)
returns integer
language plpgsql
security invoker
set search_path = public
as $$
declare
    inserted integer;
begin
    -- `where true`: Supabase's safeupdate guard rejects a delete without a where clause.
    delete from public.park_wind_forecast where true;

    insert into public.park_wind_forecast (
        park_id, forecast_time,
        wind_speed_10m, wind_speed_100m, wind_direction_10m, wind_direction_100m,
        wind_gusts_10m, temperature_2m, relative_humidity_2m, dew_point_2m,
        surface_pressure, fetched_at
    )
    select
        r.park_id, r.forecast_time,
        r.wind_speed_10m, r.wind_speed_100m, r.wind_direction_10m, r.wind_direction_100m,
        r.wind_gusts_10m, r.temperature_2m, r.relative_humidity_2m, r.dew_point_2m,
        r.surface_pressure, coalesce(r.fetched_at, now())
    from jsonb_to_recordset(rows) as r(
        park_id              bigint,
        forecast_time        timestamptz,
        wind_speed_10m       real,
        wind_speed_100m      real,
        wind_direction_10m   real,
        wind_direction_100m  real,
        wind_gusts_10m       real,
        temperature_2m       real,
        relative_humidity_2m real,
        dew_point_2m         real,
        surface_pressure     real,
        fetched_at           timestamptz
    );

    get diagnostics inserted = row_count;
    return inserted;
end;
$$;

-- Only the background job (service role) may overwrite the forecast; the frontend only reads.
revoke all on function public.replace_park_wind_forecast(jsonb) from public, anon, authenticated;
grant execute on function public.replace_park_wind_forecast(jsonb) to service_role;
