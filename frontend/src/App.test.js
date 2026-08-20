import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

jest.mock('./api', () => ({
  __esModule: true,
  default: { post: jest.fn() },
}));

import api from './api';
import App from './App';

beforeEach(() => {
  api.post.mockReset();
});

test('renders the chat greeting and query input', () => {
  render(<App />);

  expect(screen.getByText(/Hello! I'm Scheduler AI/i)).toBeInTheDocument();
  expect(screen.getByPlaceholderText(/Ask anything/i)).toBeInTheDocument();
});

test('clicking a create-flow button does not crash (regression for handleButtonClick scoping bug)', async () => {
  // Regression guard: handleButtonClick/renderCreateFlowMessage used to be
  // defined outside the App component, so calling handleButtonClick threw
  // "setMessages is not defined" the moment a button was clicked.
  api.post.mockImplementation((url, body) => {
    if (body.action === 'reminders_due') {
      return Promise.resolve({ data: { due_reminders: [] } });
    }
    if (body.query === 'create appointment') {
      return Promise.resolve({
        data: {
          flow: 'create_appointment',
          status: 'need_more_info',
          awaiting: 'date',
          message: 'When should I schedule it?',
          buttons: [{ label: 'Today', value: 'today' }],
        },
      });
    }
    if (body.query === 'today') {
      return Promise.resolve({
        data: {
          flow: 'create_appointment',
          status: 'need_more_info',
          awaiting: 'time',
          message: 'What time?',
          buttons: [{ label: '9:00 AM', value: '9:00 am' }],
        },
      });
    }
    return Promise.resolve({ data: {} });
  });

  render(<App />);

  const input = screen.getByPlaceholderText(/Ask anything/i);
  await userEvent.type(input, 'create appointment');
  await userEvent.click(screen.getByRole('button', { name: 'Send' }));

  const todayButton = await screen.findByRole('button', { name: 'Today' });
  await userEvent.click(todayButton);

  // If handleButtonClick had thrown, this text (from the next flow step)
  // would never render.
  expect(await screen.findByRole('button', { name: '9:00 AM' })).toBeInTheDocument();
});

test('a free-text query mentioning "today" is sent as-is, not silently replaced (regression)', async () => {
  // Regression guard: handleQuery used to classify any query that didn't
  // match a hardcoded list of keywords (schedule/cancel/free/between/...)
  // and also contained "today"/"this week" by silently discarding its
  // entire text and sending {action:'today'} instead. This broke things
  // like "remind me at 5pm today to call Alex" and "how many meetings
  // today" — both mention "today" but match none of those keywords.
  api.post.mockImplementation((url, body) => {
    if (body.action === 'reminders_due') {
      return Promise.resolve({ data: { due_reminders: [] } });
    }
    return Promise.resolve({ data: { reminder: { id: 1, title: 'call Alex' } } });
  });

  render(<App />);
  const input = screen.getByPlaceholderText(/Ask anything/i);
  await userEvent.type(input, 'remind me at 5pm today to call Alex');
  await userEvent.click(screen.getByRole('button', { name: 'Send' }));

  await screen.findByText(/call Alex/i);

  const queryCalls = api.post.mock.calls.filter(([, body]) => body && body.query);
  expect(queryCalls.length).toBeGreaterThan(0);
  expect(queryCalls[queryCalls.length - 1][1]).toEqual({
    query: 'remind me at 5pm today to call Alex',
  });
});

test('recurring preview (flat array under data.preview) renders in Proposed Slots (regression)', async () => {
  // Regression guard: applyPayload checked `typeof data.preview === 'object'`
  // to detect a nested payload — but every real backend response sets
  // `preview` to a flat array, and `typeof [] === 'object'` is true in JS,
  // so it always recursed into the array itself (which has none of the
  // fields applyPayload looks for) and silently dropped the data —
  // "No proposals yet." even though the backend returned real slots.
  api.post.mockImplementation((url, body) => {
    if (body.action === 'reminders_due') {
      return Promise.resolve({ data: { due_reminders: [] } });
    }
    return Promise.resolve({
      data: {
        preview: [
          { date: '2026-08-24', start_time: '10:00:00', end_time: '11:00:00', title: 'standup' },
        ],
      },
    });
  });

  render(<App />);
  const input = screen.getByPlaceholderText(/Ask anything/i);
  await userEvent.type(input, 'preview standup every Monday at 10am for 3 weeks');
  await userEvent.click(screen.getByRole('button', { name: 'Send' }));

  expect(await screen.findByText('standup')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Book this' })).toBeInTheDocument();
});

test('dismissing a reminder toast sends the correct payload shape (regression)', async () => {
  // Regression guard: markReminderDelivered called api.post('/query', {
  // method, headers, body: JSON.stringify(...) }) — fetch()-style options
  // passed as axios's data argument, so axios sent that literal object as
  // the JSON body instead of {action, id}. The backend always rejected it
  // with a 400, and the promise rejection was never caught, crashing with
  // an uncaught runtime error every time a user dismissed a due-reminder
  // toast.
  api.post.mockImplementation((url, body) => {
    if (body.action === 'reminders_due') {
      return Promise.resolve({
        data: {
          due_reminders: [
            { id: 42, title: 'call Alex', date: '2026-08-19', time: '17:00:00' },
          ],
        },
      });
    }
    return Promise.resolve({ data: {} });
  });

  render(<App />);

  const dismissBtn = await screen.findByRole('button', { name: /dismiss/i });
  await userEvent.click(dismissBtn);

  const deliveredCall = api.post.mock.calls.find(
    ([, body]) => body && body.action === 'reminder_mark_delivered'
  );
  expect(deliveredCall).toBeTruthy();
  expect(deliveredCall[1]).toEqual({ action: 'reminder_mark_delivered', id: 42 });
});
