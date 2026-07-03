class Basic:
    class Deliver:
        delivery_tag: int

    class GetOk:
        delivery_tag: int


class Queue:
    class DeclareOk:
        message_count: int | None
