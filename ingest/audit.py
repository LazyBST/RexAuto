import json


def log(cur, actor, event_type, batch_id=None, product_id=None, **details):
    cur.execute(
        "insert into audit_events(actor, event_type, batch_id, product_id, details) values (%s,%s,%s,%s,%s)",
        (actor, event_type, batch_id, product_id, json.dumps(details, default=str)),
    )
