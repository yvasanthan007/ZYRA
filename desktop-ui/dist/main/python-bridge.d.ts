interface Command {
    type: string;
    data: unknown;
}
export declare class PythonBridge {
    private process;
    private requestId;
    private pendingRequests;
    private buffer;
    start(): void;
    stop(): void;
    sendCommand(command: Command): Promise<unknown>;
    private processBuffer;
    isRunning(): boolean;
}
export {};
//# sourceMappingURL=python-bridge.d.ts.map