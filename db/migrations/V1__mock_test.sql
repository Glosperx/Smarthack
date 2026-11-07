create table if not exists mock_table (
    id   bigint generated always as identity primary key,
    text varchar(100) not null
);
