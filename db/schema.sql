-- Subscriber storage for planning alerts.
--
-- Run once against the Postgres behind the project (Supabase SQL editor, or
-- psql). The Netlify functions reach this through PostgREST with the service
-- role key; the notify script reaches it the same way. Nothing here is ever
-- exposed to the browser directly -- see the row level security block at the
-- bottom, which is the part that makes that true rather than merely intended.

create table if not exists subscribers (
  id              bigserial primary key,
  email           text        not null,
  -- lowercased, for uniqueness. The display copy keeps whatever the person
  -- typed, because an address is theirs to capitalise as they like.
  email_norm      text        not null unique,
  -- GSS codes (E06000001, S12000049, ...). Matching the register's own
  -- identifiers means a council rename never orphans a subscription.
  areas           text[]      not null default '{}',

  -- Double opt-in. An unconfirmed row is not a subscriber, it is an intent,
  -- and the notify script never reads it.
  confirmed       boolean     not null default false,
  confirm_token   text,
  confirm_sent_at timestamptz,
  confirmed_at    timestamptz,

  -- The consent record. UK GDPR asks you to show *when* and *how* consent was
  -- given, not merely to assert that it was.
  created_at      timestamptz not null default now(),
  consent_ip      inet,
  consent_ua      text,

  unsubscribed_at timestamptz,
  bounce_count    int         not null default 0,
  last_sent_at    timestamptz
);

create index if not exists subscribers_active_idx
  on subscribers (confirmed)
  where confirmed and unsubscribed_at is null;

-- Idempotency. The diff decides what is new; this decides what has already
-- gone out, so a bad snapshot, a re-run, or a restored backup cannot send the
-- same application to the same person twice.
create table if not exists sent_alerts (
  subscriber_id bigint      not null references subscribers(id) on delete cascade,
  ref           text        not null,
  sent_at       timestamptz not null default now(),
  primary key (subscriber_id, ref)
);

create index if not exists sent_alerts_ref_idx on sent_alerts (ref);

-- Every send, for debugging deliverability and for answering "what did you
-- send me and when". Deliberately holds no message body.
create table if not exists send_log (
  id            bigserial primary key,
  subscriber_id bigint      references subscribers(id) on delete set null,
  area_code     text,
  n_refs        int         not null,
  provider_id   text,
  ok            boolean     not null,
  error         text,
  sent_at       timestamptz not null default now()
);

-- Row level security. PostgREST honours these; the service role key used by
-- the functions bypasses them. Without this block the anon key could read the
-- whole subscriber list, which is the single worst thing that could happen
-- here, so it is on by default with no policy granting anon anything.
alter table subscribers  enable row level security;
alter table sent_alerts  enable row level security;
alter table send_log     enable row level security;

revoke all on subscribers, sent_alerts, send_log from anon, authenticated;
