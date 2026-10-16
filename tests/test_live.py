import time

from rameau.livesynth import Channel, NoteEvent, Player, Program


class FakeSynth:
    def __init__(self):
        self.log = []
        self.t0 = time.perf_counter()

    def _rec(self, *e):
        self.log.append((time.perf_counter() - self.t0, *e))

    def noteon(self, ch, key, vel): self._rec("on", ch, key, vel)
    def noteoff(self, ch, key): self._rec("off", ch, key)
    def cc(self, ch, ctrl, value): self._rec("cc", ch, ctrl, value)
    def program(self, ch, prog): self._rec("prog", ch, prog)
    def all_notes_off(self): self._rec("panic")


def make(n=8, step=0.1, pitch=60, ch=0):
    notes = [NoteEvent(i * step, i * step + step * 0.9, ch, pitch + i, 80) for i in range(n)]
    return Program(notes, {ch: Channel("Test", 0)}, [i * step * 4 for i in range(n // 4 + 1)], n * step)


def test_notes_play_on_time():
    synth = FakeSynth()
    player = Player(synth)
    player.load(make())
    synth.t0 = time.perf_counter()
    player.play(0.0)
    time.sleep(1.0)
    ons = [e for e in synth.log if e[1] == "on"]
    assert [e[3] for e in ons] == list(range(60, 68))
    errors = [abs(e[0] - i * 0.1) for i, e in enumerate(ons)]
    assert max(errors) < 0.02, errors      # within 20 ms on a busy test machine
    assert not player.playing               # stopped at the end


def test_instant_mixer_change_and_mute():
    synth = FakeSynth()
    player = Player(synth)
    player.load(make())
    player.set_channel(0, volume=30, program=40)
    assert ("cc", 0, 7, 30) in [e[1:] for e in synth.log]
    assert ("prog", 0, 40) in [e[1:] for e in synth.log]
    player.set_channel(0, mute=True)
    assert ("cc", 0, 7, 0) in [e[1:] for e in synth.log]


def test_swap_replaces_music_ahead_of_the_playhead():
    synth = FakeSynth()
    player = Player(synth)
    player.load(make(n=16, step=0.05))
    player.play(0.0)
    time.sleep(0.2)
    player.swap(make(n=16, step=0.05, pitch=80), at="now")
    time.sleep(0.8)
    pitches = [e[3] for e in synth.log if e[1] == "on"]
    assert any(p < 70 for p in pitches) and any(p >= 80 for p in pitches)
    assert all(p >= 80 for p in pitches[pitches.index(next(p for p in pitches if p >= 80)):])


def test_loop_repeats_a_section():
    synth = FakeSynth()
    player = Player(synth)
    player.load(make(n=8, step=0.05))
    player.loop = (0.0, 0.2)
    player.play(0.0)
    time.sleep(0.7)
    player.stop()
    first = [e[3] for e in synth.log if e[1] == "on"].count(60)
    assert first >= 3                        # the first note came round again and again


def test_mixer_settings_survive_a_swap():
    synth = FakeSynth()
    player = Player(synth)
    player.load(make())
    player.set_channel(0, mute=True, volume=55, program=40)
    new = make(pitch=70)
    player.swap(new)
    c = player.program.channels[0]
    assert (c.mute, c.volume, c.program) == (True, 55, 40)
