import fakeredis

from drugtime.runtime.scheduler import TICK_JOB_ID, ensure_schedules


def test_tick_is_registered_once_and_restored_after_redis_loss():
    redis = fakeredis.FakeRedis()
    assert ensure_schedules(redis) is True
    assert ensure_schedules(redis) is False  # idempotent
    redis.flushall()  # mô phỏng Redis mất dữ liệu
    assert ensure_schedules(redis) is True

    from rq_scheduler import Scheduler

    assert [j.id for j in Scheduler(connection=redis).get_jobs()] == [TICK_JOB_ID]
