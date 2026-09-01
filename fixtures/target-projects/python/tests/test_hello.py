from src.hello import greeting


def test_greeting() -> None:
    assert greeting("world") == "hello, world"
