from postprocess.base import PostProcessor, PostProcessResult, run_postprocessors


class OkProcessor(PostProcessor):
    name = "ok"

    def run(self, video_path, audio_path, progress_cb):
        progress_cb(1.0)
        return PostProcessResult(name=self.name, success=True,
                                 output_path="out.srt")


class BoomProcessor(PostProcessor):
    name = "boom"

    def run(self, video_path, audio_path, progress_cb):
        raise RuntimeError("explosion")


def test_runner_collects_results_in_order():
    results = run_postprocessors([OkProcessor(), OkProcessor()],
                                 "v.mp4", "a.wav", lambda p: None)
    assert [r.success for r in results] == [True, True]


def test_runner_never_raises_and_continues_after_failure():
    results = run_postprocessors([BoomProcessor(), OkProcessor()],
                                 "v.mp4", "a.wav", lambda p: None)
    assert results[0].success is False
    assert "explosion" in results[0].error
    assert results[1].success is True


def test_runner_reports_global_progress_and_steps():
    progress, steps = [], []
    run_postprocessors([OkProcessor(), OkProcessor()], "v.mp4", None,
                       progress.append, step_cb=steps.append)
    assert steps == ["ok", "ok"]
    assert progress[-1] == 1.0
    assert all(0.0 <= p <= 1.0 for p in progress)
