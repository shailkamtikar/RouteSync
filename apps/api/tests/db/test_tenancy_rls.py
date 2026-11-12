import psycopg
import pytest

from .conftest import add_member, make_user

pytestmark = pytest.mark.db


def ids(conn, sql, params=()):
    return {row[0] for row in conn.execute(sql, params).fetchall()}


def expect_error(conn, error_type, sql, params=()):
    with pytest.raises(error_type):
        with conn.transaction():  # savepoint, so the outer transaction survives
            conn.execute(sql, params)


def test_member_sees_only_own_operator(conn, actor, tenants):
    actor.user(tenants["owner1"])
    assert ids(conn, "select id from public.operators") == {tenants["op1"]}


def test_cross_operator_read_returns_nothing(conn, actor, tenants):
    actor.user(tenants["owner1"])
    assert ids(conn, "select id from public.operators where id = %s", (tenants["op2"],)) == set()
    assert (
        ids(
            conn,
            "select id from public.operator_members where operator_id = %s",
            (tenants["op2"],),
        )
        == set()
    )


def test_member_sees_colleagues_but_not_other_operators_members(conn, actor, tenants):
    actor.user(tenants["dispatcher1"])
    assert ids(conn, "select user_id from public.operator_members") == {
        tenants["owner1"],
        tenants["dispatcher1"],
    }


def test_user_without_membership_sees_nothing(conn, actor, tenants):
    actor.user(tenants["outsider"])
    assert ids(conn, "select id from public.operators") == set()
    assert ids(conn, "select id from public.operator_members") == set()


def test_anon_has_no_access(conn, actor, tenants):
    actor.anon()
    expect_error(conn, psycopg.errors.InsufficientPrivilege, "select id from public.operators")
    expect_error(
        conn, psycopg.errors.InsufficientPrivilege, "select id from public.operator_members"
    )


def test_owner_can_add_member_to_own_operator(conn, actor, tenants):
    actor.admin()
    newcomer = make_user(conn)
    actor.user(tenants["owner1"])
    add_member(conn, tenants["op1"], newcomer, "dispatcher")
    assert newcomer in ids(conn, "select user_id from public.operator_members")


def test_dispatcher_cannot_add_member(conn, actor, tenants):
    actor.admin()
    newcomer = make_user(conn)
    actor.user(tenants["dispatcher1"])
    expect_error(
        conn,
        psycopg.errors.InsufficientPrivilege,
        "insert into public.operator_members (operator_id, user_id, role) values (%s, %s, %s)",
        (tenants["op1"], newcomer, "dispatcher"),
    )


def test_owner_cannot_add_member_to_other_operator(conn, actor, tenants):
    actor.admin()
    newcomer = make_user(conn)
    actor.user(tenants["owner1"])
    expect_error(
        conn,
        psycopg.errors.InsufficientPrivilege,
        "insert into public.operator_members (operator_id, user_id, role) values (%s, %s, %s)",
        (tenants["op2"], newcomer, "owner"),
    )


def test_dispatcher_cannot_promote_self(conn, actor, tenants):
    actor.user(tenants["dispatcher1"])
    updated = conn.execute(
        "update public.operator_members set role = 'owner' where user_id = %s",
        (tenants["dispatcher1"],),
    ).rowcount
    assert updated == 0
    actor.admin()
    role = conn.execute(
        "select role from public.operator_members where user_id = %s", (tenants["dispatcher1"],)
    ).fetchone()[0]
    assert role == "dispatcher"


def test_owner_cannot_move_member_to_other_operator(conn, actor, tenants):
    actor.user(tenants["owner1"])
    expect_error(
        conn,
        psycopg.errors.InsufficientPrivilege,
        "update public.operator_members set operator_id = %s where user_id = %s",
        (tenants["op2"], tenants["dispatcher1"]),
    )


def test_owner_cannot_delete_other_operators_member(conn, actor, tenants):
    actor.user(tenants["owner1"])
    deleted = conn.execute(
        "delete from public.operator_members where user_id = %s", (tenants["owner2"],)
    ).rowcount
    assert deleted == 0


def test_authenticated_cannot_write_operators(conn, actor, tenants):
    actor.user(tenants["owner1"])
    expect_error(
        conn,
        psycopg.errors.InsufficientPrivilege,
        "update public.operators set name = 'hacked' where id = %s",
        (tenants["op1"],),
    )
    expect_error(
        conn,
        psycopg.errors.InsufficientPrivilege,
        "insert into public.operators (name) values ('rogue')",
    )


def test_duplicate_membership_rejected(conn, actor, tenants):
    actor.admin()
    expect_error(
        conn,
        psycopg.errors.UniqueViolation,
        "insert into public.operator_members (operator_id, user_id, role) values (%s, %s, %s)",
        (tenants["op2"], tenants["owner1"], "dispatcher"),
    )


def test_invalid_role_rejected(conn, actor, tenants):
    actor.admin()
    newcomer = make_user(conn)
    expect_error(
        conn,
        psycopg.errors.CheckViolation,
        "insert into public.operator_members (operator_id, user_id, role) values (%s, %s, %s)",
        (tenants["op1"], newcomer, "admin"),
    )


def test_rls_enabled_on_all_public_tables(conn, actor):
    actor.admin()
    unprotected = ids(
        conn,
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity "
        "and c.relname <> 'spatial_ref_sys'",
    )
    assert unprotected == set()
