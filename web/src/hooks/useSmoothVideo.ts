import { useCallback, useEffect, useRef, useState } from "react";
import type { Talk } from "@/hooks/useTalk";
import { fetchJson } from "@/lib/http";
import { CONNECT_TIMEOUT_MS, HELLO_AGAIN_MS, MAX_PEERS, RETRY_MS, RTC_REFRESH_MS, capEncoding, isOfferer, type RtcReply } from "@/lib/smoothVideo";

interface Peer {
  connection: RTCPeerConnection;
  session: string; // the offer's id, which its answer and every candidate carry: anything for an older one is dropped
  waiting: RTCIceCandidateInit[]; // candidates that came before the other side's description
}

interface Signal {
  hello?: boolean; // the answering side asking for a fresh offer (it just came, or came back)
  session?: string;
  description?: RTCSessionDescriptionInit;
  candidate?: RTCIceCandidateInit;
}

interface SmoothVideoInput {
  talk: Talk; // its socket carries the signaling
  me: string | undefined;
  peers: string[]; // everyone else here
  track: MediaStreamTrack | null; // your camera while you may send it (findSendingTrack), else null
}

// Whether the Pi has smooth video on, and the ICE servers for it (GET /api/rtc), asked again every RTC_REFRESH_MS.
export function useRtc(): RtcReply | null {
  const [rtc, setRtc] = useState<RtcReply | null>(null);
  useEffect(() => {
    const ask = () => void fetchJson<RtcReply>("/api/rtc").then((reply) => setRtc(reply ?? { smooth_video: false, ice_servers: [] }));
    ask();
    const timer = window.setInterval(ask, RTC_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, []);
  return rtc;
}

function sendOn(connection: RTCPeerConnection, track: MediaStreamTrack | null): void {
  const sender = connection.getTransceivers()[0]?.sender;
  if (sender != null) {
    void sender.replaceTrack(track).then(() => {
      const parameters = sender.getParameters();
      if (track != null && parameters.encodings?.length) {
        parameters.encodings[0] = { ...parameters.encodings[0], ...capEncoding(track) };
        void sender.setParameters(parameters).catch(() => {});
      }
    });
  }
}

// The seats' smooth video: one RTCPeerConnection to each person here (a full mesh, MAX_PEERS at most), each sending your
// camera's own track (or nothing, while you may not) and receiving theirs. The Pi only passes the signaling along on
// the talk socket. A pair that can't connect keeps its picture a second and tries again after RETRY_MS. Returns each
// person's incoming stream while their connection is up.
export function useSmoothVideo(rtc: RtcReply | null, { talk, me, peers, track }: SmoothVideoInput): Record<string, MediaStream> {
  const [streams, setStreams] = useState<Record<string, MediaStream>>({});
  const [retries, setRetries] = useState(0);
  const connections = useRef(new Map<string, Peer>());
  const failedAt = useRef(new Map<string, number>());
  const trackRef = useRef(track);
  const enabled = rtc?.smooth_video === true && me != null && talk.connected;
  const wanted = enabled ? peers.slice(0, MAX_PEERS) : [];
  const wantedKey = wanted.join("\n");
  const { sendSignal, listenSignals } = talk;
  const iceServers = rtc?.ice_servers;

  const close = useCallback((who: string) => {
    connections.current.get(who)?.connection.close();
    connections.current.delete(who);
    setStreams((current) => {
      const { [who]: _gone, ...rest } = current;
      return who in current ? rest : current;
    });
  }, []);

  // A pair that couldn't connect (or whose setup went wrong) keeps its pictures and tries again after RETRY_MS.
  const fail = useCallback(
    (who: string) => {
      failedAt.current.set(who, performance.now());
      close(who);
      window.setTimeout(() => setRetries((count) => count + 1), RETRY_MS);
    },
    [close],
  );

  const open = useCallback(
    async (who: string, offer?: RTCSessionDescriptionInit, offered?: string) => {
      close(who);
      const connection = new RTCPeerConnection({ iceServers });
      const peer: Peer = { connection, session: offered ?? crypto.randomUUID(), waiting: [] };
      const current = () => connections.current.get(who) === peer; // a newer offer may have replaced it meanwhile
      connections.current.set(who, peer);
      connection.onicecandidate = (event) => event.candidate != null && current() && sendSignal(who, { session: peer.session, candidate: event.candidate.toJSON() });
      connection.ontrack = (event) => current() && setStreams((streamsNow) => ({ ...streamsNow, [who]: event.streams[0] ?? new MediaStream([event.track]) }));
      connection.onconnectionstatechange = () => connection.connectionState === "failed" && current() && fail(who);
      // An offer or answer lost on the way leaves a connection that never fails on its own: give it CONNECT_TIMEOUT_MS.
      window.setTimeout(() => current() && connection.connectionState !== "connected" && fail(who), CONNECT_TIMEOUT_MS);
      try {
        if (offer == null) {
          connection.addTransceiver("video", { direction: "sendrecv" });
          sendOn(connection, trackRef.current);
          await connection.setLocalDescription(await connection.createOffer());
        } else {
          await connection.setRemoteDescription(offer);
          connection.getTransceivers()[0].direction = "sendrecv";
          sendOn(connection, trackRef.current);
          await Promise.all(peer.waiting.splice(0).map((candidate) => connection.addIceCandidate(candidate)));
          await connection.setLocalDescription(await connection.createAnswer());
        }
        if (current()) {
          sendOn(connection, trackRef.current); // now that it's negotiated, its encoding takes the caps
          sendSignal(who, { session: peer.session, description: connection.localDescription?.toJSON() });
        }
      } catch {
        // A setup a newer offer replaced throws once its connection closes; only a current one fails the pair.
        if (current()) {
          fail(who);
        }
      }
    },
    [close, fail, iceServers, sendSignal],
  );

  // Hide, away or unknown: every sender drops your camera at once (replaceTrack(null)); back, it picks it up again.
  useEffect(() => {
    trackRef.current = track;
    connections.current.forEach(({ connection }) => sendOn(connection, track));
  }, [track]);

  useEffect(() => {
    const names = wantedKey === "" ? [] : wantedKey.split("\n");
    [...connections.current.keys()].filter((who) => !names.includes(who)).forEach(close);
    const due = (who: string) => performance.now() - (failedAt.current.get(who) ?? -Infinity) >= RETRY_MS;
    names
      .filter((who) => !connections.current.has(who) && due(who) && me != null)
      .forEach((who) => {
        if (isOfferer(me!, who)) {
          void open(who);
        } else {
          sendSignal(who, { hello: true });
          window.setTimeout(() => setRetries((count) => count + 1), HELLO_AGAIN_MS); // asks again if no offer came
        }
      });
  }, [wantedKey, retries, me, open, close, fail, sendSignal]);

  useEffect(
    () =>
      listenSignals((from, raw) => {
        const signal = raw as Signal;
        const peer = connections.current.get(from);
        // Only with someone here: anyone else's signal sets nothing up.
        if (me != null && wantedKey.split("\n").includes(from)) {
          const ours = peer != null && signal.session === peer.session;
          if (signal.hello === true && isOfferer(me, from)) {
            void open(from);
          } else if (signal.description?.type === "offer" && signal.session != null) {
            void open(from, signal.description, signal.session);
          } else if (signal.description?.type === "answer" && ours) {
            void peer.connection
              .setRemoteDescription(signal.description)
              .then(() => Promise.all(peer.waiting.splice(0).map((candidate) => peer.connection.addIceCandidate(candidate))))
              .catch(() => connections.current.get(from) === peer && fail(from));
          } else if (signal.candidate != null && ours) {
            if (peer.connection.remoteDescription == null) {
              peer.waiting.push(signal.candidate);
            } else {
              void peer.connection.addIceCandidate(signal.candidate).catch(() => {});
            }
          }
        }
      }),
    [listenSignals, open, fail, wantedKey, me],
  );

  useEffect(() => () => [...connections.current.keys()].forEach(close), [close]);

  return streams;
}
