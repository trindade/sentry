# -*- coding: utf-8 -*-

from __future__ import absolute_import

import mock

from datetime import timedelta
from django.utils import timezone
from sentry.buffer.redis import RedisBuffer
from sentry.models import Group, Project
from sentry.utils.compat import pickle
from sentry.testutils import TestCase


class RedisBufferTest(TestCase):
    def setUp(self):
        self.buf = RedisBuffer(hosts={
            0: {'db': 9}
        })
        self.buf.conn.flushdb()

    def test_default_host_is_local(self):
        buf = RedisBuffer()
        self.assertEquals(len(buf.conn.hosts), 1)
        self.assertEquals(buf.conn.hosts[0].host, 'localhost')

    def test_coerce_val_handles_foreignkeys(self):
        assert self.buf._coerce_val(Project(id=1)) == '1'

    def test_coerce_val_handles_unicode(self):
        assert self.buf._coerce_val(u'\u201d') == '”'

    def test_make_key_response(self):
        column = 'times_seen'
        filters = {'pk': 1}
        self.assertEquals(self.buf._make_key(Group, filters, column), 'sentry.group:88b48b31b5f100719c64316596b10b0f:times_seen')

    def test_make_extra_key_response(self):
        filters = {'pk': 1}
        self.assertEquals(self.buf._make_extra_key(Group, filters), 'sentry.group:extra:88b48b31b5f100719c64316596b10b0f')

    @mock.patch('sentry.buffer.redis.RedisBuffer._make_extra_key', mock.Mock(return_value='extra'))
    @mock.patch('sentry.buffer.redis.RedisBuffer._make_key', mock.Mock(return_value='foo'))
    @mock.patch('sentry.buffer.base.process_delay')
    def test_delay_delays_task(self, process_delay):
        model = mock.Mock()
        columns = {'times_seen': 1}
        filters = {'pk': 1}
        self.buf.delay(model, columns, filters)
        kwargs = dict(model=model, columns=columns, filters=filters, extra=None)
        process_delay.apply_async.assert_called_once_with(
            kwargs=kwargs, countdown=5)

    @mock.patch('sentry.buffer.redis.RedisBuffer._make_extra_key', mock.Mock(return_value='extra'))
    @mock.patch('sentry.buffer.redis.RedisBuffer._make_key', mock.Mock(return_value='foo'))
    @mock.patch('sentry.buffer.base.process_delay', mock.Mock())
    def test_delay_does_buffer_to_conn(self):
        model = mock.Mock()
        columns = {'times_seen': 1}
        filters = {'pk': 1}
        self.buf.delay(model, columns, filters)
        assert self.buf.conn.get('foo') == '1'

    @mock.patch('sentry.buffer.redis.RedisBuffer._make_extra_key', mock.Mock(return_value='extra'))
    @mock.patch('sentry.buffer.redis.RedisBuffer._make_key', mock.Mock(return_value='foo'))
    @mock.patch('sentry.buffer.base.Buffer.process_delay')
    def test_process_delay_does_not_save_empty_results(self, process_delay):
        group = Group.objects.create(project=Project(id=1))
        columns = {'times_seen': 1}
        filters = {'pk': group.pk}
        self.buf.process_delay(Group, columns, filters)
        assert not process_delay.called

    @mock.patch('sentry.buffer.redis.RedisBuffer._make_extra_key', mock.Mock(return_value='extra'))
    @mock.patch('sentry.buffer.redis.RedisBuffer._make_key', mock.Mock(return_value='foo'))
    @mock.patch('sentry.buffer.base.Buffer.process_delay')
    def test_process_delay_does_save_call_with_results(self, process_delay):
        group = Group.objects.create(project=Project(id=1))
        columns = {'times_seen': 1}
        filters = {'pk': group.pk}
        self.buf.conn.set('foo', 2)
        self.buf.process_delay(Group, columns, filters)
        process_delay.assert_called_once_with(Group, {'times_seen': 2}, filters, None)

    @mock.patch('sentry.buffer.redis.RedisBuffer._make_extra_key', mock.Mock(return_value='extra'))
    @mock.patch('sentry.buffer.redis.RedisBuffer._make_key', mock.Mock(return_value='foo'))
    @mock.patch('sentry.buffer.base.Buffer.process_delay', mock.Mock())
    def test_process_delay_does_clear_buffer(self):
        group = Group.objects.create(project=Project(id=1))
        columns = {'times_seen': 1}
        filters = {'pk': group.pk}
        self.buf.conn.set('foo', 2)
        self.buf.process_delay(Group, columns, filters)
        assert self.buf.conn.get('foo') is None

    @mock.patch('sentry.buffer.redis.RedisBuffer._make_extra_key', mock.Mock(return_value='extra'))
    @mock.patch('sentry.buffer.redis.RedisBuffer._make_key', mock.Mock(return_value='foo'))
    @mock.patch('sentry.buffer.base.process_delay', mock.Mock())
    def test_delay_does_buffer_extra_to_conn(self):
        model = mock.Mock()
        columns = {'times_seen': 1}
        filters = {'pk': 1}
        self.buf.delay(model, columns, filters, extra={'foo': 'bar'})
        assert self.buf.conn.hget('extra', 'foo') == pickle.dumps('bar')

    @mock.patch('sentry.buffer.redis.RedisBuffer._make_key', mock.Mock(return_value='foo'))
    @mock.patch('sentry.buffer.redis.RedisBuffer._make_extra_key', mock.Mock(return_value='extra'))
    def test_process_delay_saves_extra(self):
        group = Group.objects.create(project=Project(id=1))
        columns = {'times_seen': 1}
        filters = {'pk': group.pk}
        the_date = (timezone.now() + timedelta(days=5)).replace(microsecond=0)
        self.buf.conn.set('foo', 1)
        self.buf.conn.hset('extra', 'last_seen', pickle.dumps(the_date))
        self.buf.process_delay(Group, columns, filters)
        group_ = Group.objects.get(pk=group.pk)
        assert group_.last_seen.replace(microsecond=0) == the_date
