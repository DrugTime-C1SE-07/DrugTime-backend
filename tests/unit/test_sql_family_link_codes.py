"""SqlLinkCodes (task 3.10): câu SQL và cách diễn giải kết quả, không cần DB thật."""

from uuid import uuid4

from drugtime.modules.family.adapters.outbound.sql_link_codes import SqlLinkCodes


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class FakeConnection:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((" ".join(str(statement).split()), params or {}))
        return FakeResult(self.values.pop(0))


class FakeUow:
    def __init__(self, values):
        self.connection = FakeConnection(values)


def test_sql_find_by_patient_filters_by_patient__AC6():
    patient = uuid4()
    uow = FakeUow(["ABCDEFGHJK"])

    assert SqlLinkCodes().find_by_patient(uow, patient) == "ABCDEFGHJK"
    sql, params = uow.connection.calls[0]
    assert sql == "SELECT code FROM link_codes WHERE patient_user_id = :patient_id"
    assert params == {"patient_id": patient}


def test_sql_find_by_patient_none_when_absent__AC1():
    assert SqlLinkCodes().find_by_patient(FakeUow([None]), uuid4()) is None


def test_sql_insert_if_absent_returns_inserted__AC1():
    patient = uuid4()
    uow = FakeUow(["ABCDEFGHJK"])

    assert SqlLinkCodes().insert_if_absent(uow, patient, "ABCDEFGHJK") == "ABCDEFGHJK"
    sql, params = uow.connection.calls[0]
    assert sql.startswith("INSERT INTO link_codes (patient_user_id, code)")
    assert "ON CONFLICT DO NOTHING RETURNING code" in sql
    assert params == {"patient_id": patient, "code": "ABCDEFGHJK"}
    assert len(uow.connection.calls) == 1


def test_sql_insert_if_absent_falls_back_to_existing__AC3():
    patient = uuid4()
    uow = FakeUow([None, "WINNER2345"])

    assert SqlLinkCodes().insert_if_absent(uow, patient, "LOSER23456") == "WINNER2345"
    assert uow.connection.calls[1][1] == {"patient_id": patient}


def test_sql_insert_if_absent_returns_none_on_code_collision__AC7():
    uow = FakeUow([None, None])

    assert SqlLinkCodes().insert_if_absent(uow, uuid4(), "TAKEN23456") is None
    assert len(uow.connection.calls) == 2
