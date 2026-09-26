import { useState, type FormEvent } from 'react';
import { EyeIcon, EyeOffIcon, LoaderCircleIcon, LockKeyholeIcon } from 'lucide-react';
import { Logo } from '../layout/Logo';

interface LoginScreenProps {
  busy: boolean;
  error: string | null;
  onSignIn: (email: string, password: string) => Promise<void>;
  onInput: () => void;
}

export function LoginScreen({ busy, error, onSignIn, onInput }: LoginScreenProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void onSignIn(email, password);
  };

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-canvas px-4 py-10 font-sans text-ink antialiased">
      <div
        className="pointer-events-none absolute inset-0 opacity-80"
        style={{
          background:
            'radial-gradient(circle at 50% 0%, rgba(62, 207, 142, 0.12), transparent 36%), radial-gradient(circle at 100% 100%, rgba(126, 166, 240, 0.08), transparent 30%)'
        }}
        aria-hidden="true"
      />

      <section className="relative w-full max-w-[420px]">
        <div className="mb-8 flex justify-center">
          <Logo />
        </div>

        <div className="rounded-2xl border border-line bg-surface p-6 shadow-2xl shadow-black/30 sm:p-8">
          <div className="mb-7">
            <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl border border-profit/20 bg-profit/10 text-profit">
              <LockKeyholeIcon className="h-5 w-5" aria-hidden="true" />
            </div>
            <h1 className="text-2xl font-semibold tracking-tight">Sign in to PMJEV</h1>
            <p className="mt-2 text-sm leading-6 text-muted">
              Continue to your private paper-trading dashboard.
            </p>
          </div>

          <form className="space-y-5" onSubmit={submit}>
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-ink">Email</span>
              <input
                type="email"
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  onInput();
                }}
                autoComplete="email"
                inputMode="email"
                required
                disabled={busy}
                placeholder="you@example.com"
                className="h-11 w-full rounded-lg border border-line bg-canvas px-3.5 text-sm text-ink outline-none transition placeholder:text-subtle focus:border-profit/70 focus:ring-2 focus:ring-profit/15 disabled:cursor-not-allowed disabled:opacity-60"
              />
            </label>

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-ink">Password</span>
              <span className="relative block">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    onInput();
                  }}
                  autoComplete="current-password"
                  required
                  disabled={busy}
                  placeholder="Enter your password"
                  className="h-11 w-full rounded-lg border border-line bg-canvas px-3.5 pr-11 text-sm text-ink outline-none transition placeholder:text-subtle focus:border-profit/70 focus:ring-2 focus:ring-profit/15 disabled:cursor-not-allowed disabled:opacity-60"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((visible) => !visible)}
                  disabled={busy}
                  className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-subtle transition hover:text-ink disabled:cursor-not-allowed disabled:opacity-60"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? (
                    <EyeOffIcon className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <EyeIcon className="h-4 w-4" aria-hidden="true" />
                  )}
                </button>
              </span>
            </label>

            {error && (
              <div
                className="rounded-lg border border-loss/30 bg-loss/10 px-3.5 py-3 text-sm text-loss"
                role="alert"
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy || !email.trim() || !password}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-ink px-4 text-sm font-semibold text-canvas transition hover:bg-white focus:outline-none focus:ring-2 focus:ring-profit focus:ring-offset-2 focus:ring-offset-surface disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy && <LoaderCircleIcon className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-xs text-subtle">
          Authorized access only · Paper trading uses simulated funds
        </p>
      </section>
    </main>
  );
}

export function AuthLoadingScreen() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas font-sans text-ink">
      <div className="flex flex-col items-center gap-4" role="status">
        <Logo />
        <LoaderCircleIcon className="h-5 w-5 animate-spin text-profit" aria-hidden="true" />
        <span className="sr-only">Checking your session</span>
      </div>
    </main>
  );
}
