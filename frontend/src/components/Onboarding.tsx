import { ArrowRight, Loader2, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";

type OnboardingProps = {
  email: string;
  password: string;
  error: string;
  setEmail: (value: string) => void;
  setPassword: (value: string) => void;
  bootstrap: () => Promise<boolean>;
  openWorkspace: () => void;
};

export function Onboarding(props: OnboardingProps) {
  const [signingIn, setSigningIn] = useState(false);

  async function signIn() {
    setSigningIn(true);
    const ok = await props.bootstrap();
    setSigningIn(false);
    if (ok) props.openWorkspace();
  }

  return (
    <main className="launch-screen">
      <section className="launch-panel">
        <div className="launch-brand">
          <Sparkles size={24} />
          <div>
            <strong>DataClaw</strong>
            <span>Agents that know. Agents that act.</span>
          </div>
        </div>

        <div className="launch-copy">
          <h1>Sign in</h1>
          <span>Connect your stack from the Gateway after signing in.</span>
        </div>

        {props.error ? <div className="settings-error" role="alert">{props.error}</div> : null}

        <div className="launch-form">
          <label>
            <span>Email</span>
            <input
              aria-label="Admin email"
              value={props.email}
              onChange={(event) => props.setEmail(event.target.value)}
            />
          </label>
          <label>
            <span>Password</span>
            <input
              aria-label="Admin password"
              type="password"
              placeholder="ADMIN_PASSWORD from .env"
              value={props.password}
              onChange={(event) => props.setPassword(event.target.value)}
            />
          </label>
        </div>

        <footer>
          <button className="primary" onClick={signIn} type="button">
            {signingIn ? <Loader2 className="spin" size={15} /> : <ShieldCheck size={15} />}
            Sign in <ArrowRight size={15} />
          </button>
        </footer>
      </section>
    </main>
  );
}
