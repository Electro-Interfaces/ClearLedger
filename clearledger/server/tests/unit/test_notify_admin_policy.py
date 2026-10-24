"""Проверка политики доставки без подключения к базе и отправки сообщений."""
import types
import unittest
import uuid
from unittest.mock import AsyncMock, patch
from sqlalchemy.dialects import postgresql

from app.services import notify

class NotificationPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_secretary_blocks_regular_user_before_side_effects(self):
        db = types.SimpleNamespace(get=AsyncMock(return_value=types.SimpleNamespace(
            customization={"system_notifications_admin_only": True})))
        with patch.object(notify, "_secretary", AsyncMock()) as secretary:
            result = await notify.notify_person(db, uuid.uuid4(),
                types.SimpleNamespace(is_superadmin=False), "private reminder")
        self.assertIsNone(result)
        secretary.assert_not_awaited()

    async def test_alerts_block_nonadmin_even_if_called_directly(self):
        with patch.object(notify, "_admins_only", AsyncMock(return_value=True)), \
             patch.object(notify, "_secretary", AsyncMock()) as secretary:
            result = await notify.post_alert(object(), uuid.uuid4(),
                [types.SimpleNamespace(is_superadmin=False)], "alert")
        self.assertFalse(result)
        secretary.assert_not_awaited()

    async def test_recipients_use_system_role_even_with_explicit_nonadmin_ids(self):
        result = types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: []))
        db = types.SimpleNamespace(execute=AsyncMock(return_value=result))
        with patch.object(notify, "_admins_only", AsyncMock(return_value=True)):
            await notify._recipients(db, uuid.uuid4(),
                types.SimpleNamespace(recipients=[str(uuid.uuid4())]))
        sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn("users.is_superadmin IS true", sql)
        self.assertNotIn("users.id IN", sql)

    async def test_existing_spaces_keep_policy_disabled(self):
        for company in (None, types.SimpleNamespace(customization=None),
                        types.SimpleNamespace(customization={})):
            db = types.SimpleNamespace(get=AsyncMock(return_value=company))
            self.assertFalse(await notify._admins_only(db, uuid.uuid4()))

    async def test_system_admin_passes_secretary_gate(self):
        class PassedGate(Exception): pass
        with patch.object(notify, "_admins_only", AsyncMock(return_value=True)), \
             patch.object(notify, "_secretary", AsyncMock(side_effect=PassedGate)):
            with self.assertRaises(PassedGate):
                await notify.notify_person(object(), uuid.uuid4(),
                    types.SimpleNamespace(is_superadmin=True), "admin reminder")

if __name__ == '__main__':
    unittest.main()
