import asyncio

import pytest

from dayanpi.focus.talk import FRAME_BURST, FRAME_MAX_BYTES, TO_EVERYONE, TO_YOU, TalkError, TalkFrame, TalkRoom, pack_frame, read_frame

EVERYONE_HEARS = {"hear_room": True, "direct_talk": True}


def message(target: str, opus: bytes = b"\x01\x02") -> bytes:
    name = target.encode()
    return bytes([len(name)]) + name + opus


def test_a_frame_is_its_target_then_the_opus():
    assert read_frame(message("")) == TalkFrame(None, b"\x01\x02")
    assert read_frame(message("sam", b"x" * FRAME_MAX_BYTES)) == TalkFrame("sam", b"x" * FRAME_MAX_BYTES)
    assert pack_frame(TO_YOU, "bo", b"\x09") == b"\x01\x02bo\x09"


@pytest.mark.parametrize(
    "bad",
    [b"", b"\x00", b"\x03sa", b"\x03sam", message("sam", b"x" * (FRAME_MAX_BYTES + 1)), b"\x21" + b"a" * 33 + b"x", b"\x02\xff\xfe\x01"],
    ids=["empty", "no frame", "cut short", "target but no frame", "frame too big", "target too long", "target not text"],
)
def test_anything_else_is_malformed(bad):
    with pytest.raises(TalkError):
        read_frame(bad)


def make_room(*names: str) -> tuple:
    room = TalkRoom()
    listeners = {name: room.join(name) for name in names}
    return room, listeners


def drain(listener) -> list[bytes]:
    got = []
    while not listener.queue.empty():
        got.append(listener.queue.get_nowait())
    return got


def test_everyone_means_everyone_here_but_the_talker_and_one_means_just_them():
    async def run():
        room, people = make_room("dayan", "sam", "al")
        sharing = {"dayan": EVERYONE_HEARS, "sam": EVERYONE_HEARS, "al": EVERYONE_HEARS}
        assert room.route(people["dayan"], TalkFrame(None, b"hi"), sharing.get, 0.0) == 2
        assert room.route(people["dayan"], TalkFrame("sam", b"psst"), sharing.get, 0.0) == 1
        assert room.route(people["dayan"], TalkFrame("dayan", b"me"), sharing.get, 0.0) == 0, "not to yourself"
        assert room.route(people["dayan"], TalkFrame("nobody", b"?"), sharing.get, 0.0) == 0
        return {name: drain(listener) for name, listener in people.items()}

    got = asyncio.run(run())
    assert got == {"dayan": [], "sam": [b"\x00\x05dayanhi", b"\x01\x05dayanpsst"], "al": [b"\x00\x05dayanhi"]}


def test_hear_the_room_off_gets_nothing_and_direct_talk_off_gets_nothing_meant_for_them_alone():
    async def run():
        room, people = make_room("dayan", "sam", "al")
        sharing = {"dayan": EVERYONE_HEARS, "sam": {"hear_room": False, "direct_talk": True}, "al": {"hear_room": True, "direct_talk": False}}
        counts = [room.route(people["dayan"], TalkFrame(target, b"x"), sharing.get, 0.0) for target in (None, "sam", "al")]
        return counts, {name: len(drain(listener)) for name, listener in people.items()}

    counts, got = asyncio.run(run())
    assert counts == [1, 0, 0]
    assert got == {"dayan": 0, "sam": 0, "al": 1}, "al still hears everyone"


def test_a_talker_past_fifty_frames_a_second_is_cut_off_until_it_slows_down():
    async def run():
        room, people = make_room("dayan", "sam")
        sharing = {"dayan": EVERYONE_HEARS, "sam": EVERYONE_HEARS}
        sent = [room.route(people["dayan"], TalkFrame(None, b"x"), sharing.get, 0.0) for _ in range(int(FRAME_BURST) + 5)]
        later = room.route(people["dayan"], TalkFrame(None, b"x"), sharing.get, 1.0)
        return sent, later

    sent, later = asyncio.run(run())
    assert sent.count(1) == FRAME_BURST and sent[-5:] == [0] * 5
    assert later == 1


def test_one_socket_each_the_newest_and_a_slow_listener_drops_instead_of_piling_up():
    async def run():
        room = TalkRoom()
        old = room.join("sam")
        new = room.join("sam")
        room.leave(old)  # the old one closing doesn't take the new one with it
        talker = room.join("dayan")
        for second in range(60):
            room.route(talker, TalkFrame(None, b"x"), lambda name: EVERYONE_HEARS, float(second))
        return old.replaced, new.replaced, new.queue.qsize(), old.queue.qsize()

    assert asyncio.run(run()) == (True, False, 25, 0)

