type RuntimeChild = {
  exitCode?: number | null;
  signalCode?: NodeJS.Signals | null;
  kill(signal?: NodeJS.Signals): void;
  once?(event: "exit", listener: () => void): unknown;
};

export function startRuntime(options: {
  spawn?: (command: string, args: string[], options: { stdio?: string; cwd?: string; env?: NodeJS.ProcessEnv }) => RuntimeChild;
  appDataPath: string;
  resourcesPath: string;
  fetchHealth?: () => Promise<boolean>;
  pollIntervalMs?: number;
  timeoutMs?: number;
  shutdownGraceMs?: number;
}): Promise<{ stop(): Promise<void> }>;
