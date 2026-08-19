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
