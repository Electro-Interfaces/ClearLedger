ALTER TABLE core.calendar_events
    ADD COLUMN protocol_sequence integer NOT NULL DEFAULT 2000000000;
ALTER TABLE core.calendar_events
    ADD CONSTRAINT ck_calendar_event_protocol_sequence
    CHECK (protocol_sequence >= 0 AND protocol_sequence <= 2147483647);
