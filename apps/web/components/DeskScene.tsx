"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { CSS3DObject, CSS3DRenderer } from "three/addons/renderers/CSS3DRenderer.js";
import { MOTION_SECONDS, type DeskSource, type DeskView, type StoryPhase } from "@/lib/demo-story";

type Props = { sources: DeskSource[]; view: DeskView; replay: number; onReady: (ready: boolean) => void; onMotion: (phase: StoryPhase, active: boolean) => void };
type Pose = { x: number; y: number; z: number; scale: number; angle: number; opacity: number };
type Waypoint = { time: number; x: number; y: number; z: number };
const ease = (value: number) => { const t = THREE.MathUtils.clamp(value, 0, 1); return t * t * t * (t * (t * 6 - 15) + 10); };
const mix = THREE.MathUtils.lerp;
function sample(points: Waypoint[], time: number) {
  const index = points.findIndex((point) => point.time >= time);
  const next = index < 0 ? points.length - 1 : Math.max(1, index);
  const a = points[next - 1], b = points[next], t = ease((time - a.time) / (b.time - a.time));
  return new THREE.Vector3(mix(a.x, b.x, t), mix(a.y, b.y, t), mix(a.z, b.z, t));
}
function readPose(object: CSS3DObject): Pose {
  return { x: object.position.x, y: object.position.y, z: object.position.z, scale: object.scale.x, angle: object.rotation.z, opacity: Number(object.element.style.opacity || 1) };
}
function applyPose(object: CSS3DObject, from: Pose, to: Pose, t: number) {
  object.position.set(mix(from.x, to.x, t), mix(from.y, to.y, t), mix(from.z, to.z, t));
  object.scale.setScalar(mix(from.scale, to.scale, t)); object.rotation.z = mix(from.angle, to.angle, t);
  object.element.style.opacity = String(mix(from.opacity, to.opacity, t));
}

export default function DeskScene({ sources, view, replay, onReady, onMotion }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const control = useRef<(view: DeskView, replay: number) => void>(() => {});
  const initialView = useRef(view);
  useEffect(() => {
    const root = host.current;
    if (!root) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true }); } catch { return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75)); renderer.setClearColor(0x000000, 0);
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
    renderer.domElement.className = "desk-glove-layer"; renderer.domElement.setAttribute("aria-hidden", "true");
    const html = new CSS3DRenderer(); html.domElement.className = "desk-html-layer";
    root.append(html.domElement, renderer.domElement);
    const scene = new THREE.Scene(), paperScene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 2, 0.1, 100);
    scene.add(new THREE.HemisphereLight(0xfff9e6, 0x395848, 2));
    const light = new THREE.DirectionalLight(0xfff7e9, 3.2);
    light.position.set(-4, 9, 3); light.castShadow = true; light.shadow.mapSize.set(1024, 1024);
    Object.assign(light.shadow.camera, { left: -9, right: 9, top: 7, bottom: -7, near: 0.5, far: 24 });
    light.shadow.bias = -0.001; light.shadow.normalBias = 0.025; scene.add(light);
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(14, 8), new THREE.ShadowMaterial({ opacity: 0.2 }));
    shadow.rotation.x = -Math.PI / 2; shadow.position.y = 0.035; shadow.receiveShadow = true; scene.add(shadow);
    function element(tag: string, className: string, text?: string) {
      const node = document.createElement(tag); node.className = className; if (text) node.textContent = text; return node;
    }
    function flat(node: HTMLElement, scale: number) {
      const object = new CSS3DObject(node); object.scale.setScalar(scale); object.rotation.x = -Math.PI / 2;
      node.style.userSelect = "text"; paperScene.add(object); return object;
    }
    const mat = element("div", "desk-cutting-mat"); mat.setAttribute("aria-hidden", "true");
    mat.append(element("span", "mat-title", "BUTLER / 资料台"), element("span", "mat-signature", "butler."));
    const ruler = element("div", "mat-ruler");
    for (let i = 0; i < 18; i++) ruler.append(element("span", "", String(i * 10).padStart(2, "0")));
    mat.append(ruler); flat(mat, 0.0075);
    const columns = sources.map((_, i) => sources.length === 1 ? 0 : (i - 1) * 3.62);
    const badges: HTMLElement[] = [];
    const papers = sources.map((source, i) => {
      const node = element("article", "desk-document"); node.style.background = ["#fffdf4", "#eef1e2", "#fbf4e5"][i];
      const head = element("div", "desk-document-head"), badge = element("span", "desk-document-access");
      badges.push(badge);
      head.append(element("span", "desk-source-mark", source.mark), element("span", "", source.source), badge);
      node.append(element("span", "desk-paperclip"), head, element("span", "desk-document-number", `0${i + 1}`), element("p", "desk-document-text", source.text), element("span", "desk-document-footer", source.id));
      const object = flat(node, 0.0073); object.position.set(columns[i] + [-0.3, 0.3, 0.25][i], 0.08, 0.5); object.rotation.z = [-0.1, 0.11, -0.07][i]; return object;
    });
    const trayNode = element("div", "desk-outbox"); trayNode.setAttribute("aria-hidden", "true");
    const tray = flat(trayNode, 0.0077); tray.position.set(3, 0.08, 0.18); trayNode.style.opacity = "0";
    const letterNode = element("article", "desk-letter");
    const letter = flat(letterNode, 0.0078); letter.position.set(0.8, 0.14, 3.8); letterNode.style.opacity = "0";
    const ticketNode = element("aside", "desk-access-ticket");
    const ticket = flat(ticketNode, 0.0078); ticket.position.set(-4.1, 0.3, 0.1); ticketNode.style.opacity = "0";
    const receiptNode = element("aside", "desk-receipt");
    const receipt = flat(receiptNode, 0.0078); receipt.position.set(-3.9, 0.2, 0); receiptNode.style.opacity = "0";
    const strands = sources.map((_, i) => {
      const curve = new THREE.CatmullRomCurve3([new THREE.Vector3(-4.2, 0.2, -1 + i * 0.7), new THREE.Vector3(-3.2, 0.7, -1.5 + i * 0.6), new THREE.Vector3(-2.1, 0.2, -1 + i * 0.75)]);
      const geometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(80));
      const material = new THREE.LineBasicMaterial({ color: 0xd3c392, transparent: true, opacity: 0 });
      const line = new THREE.Line(geometry, material); scene.add(line);
      const bead = new THREE.Mesh(new THREE.SphereGeometry(0.045, 12, 8), new THREE.MeshBasicMaterial({ color: 0xffe6a6, transparent: true })); scene.add(bead);
      return { curve, geometry, material, bead };
    });
    const glove = new THREE.Group(); scene.add(glove);
    const cotton = new THREE.MeshStandardMaterial({ color: 0xfff9e9, roughness: 0.72 });
    const seam = new THREE.MeshStandardMaterial({ color: 0xc8c4af, roughness: 0.8 });
    const jacket = new THREE.MeshStandardMaterial({ color: 0x244e3d, roughness: 0.87 });
    const brass = new THREE.MeshStandardMaterial({ color: 0xd5b46c, metalness: 0.7, roughness: 0.32 });
    function mesh(geometry: THREE.BufferGeometry, material: THREE.Material, parent: THREE.Object3D, position: number[], scale?: number[]) {
      const object = new THREE.Mesh(geometry, material); object.position.set(position[0], position[1], position[2]);
      if (scale) object.scale.set(scale[0], scale[1], scale[2]);
      object.castShadow = true; object.receiveShadow = true; parent.add(object); return object;
    }
    // Separate finger joints give the white glove a soft, articulated silhouette.
    mesh(new THREE.SphereGeometry(1, 32, 20), cotton, glove, [0, 0, 0], [0.49, 0.19, 0.51]);
    mesh(new THREE.SphereGeometry(1, 24, 16), cotton, glove, [0, 0.01, 0.41], [0.31, 0.17, 0.32]);
    const fingers: THREE.Group[] = [];
    for (let i = 0; i < 4; i++) {
      const finger = new THREE.Group(); finger.position.set(-0.34 + i * 0.22, 0.01, -0.3); finger.rotation.y = (i - 1.5) * -0.065;
      const length = [0.47, 0.62, 0.57, 0.4][i];
      const joint = mesh(new THREE.CapsuleGeometry(0.112, length, 6, 12), cotton, finger, [0, 0, -length / 2]); joint.rotation.x = Math.PI / 2;
      mesh(new THREE.SphereGeometry(0.114, 16, 12), cotton, finger, [0, 0.015, -length - 0.03], [1, 0.85, 1.15]);
      glove.add(finger); fingers.push(finger);
    }
    const thumb = mesh(new THREE.CapsuleGeometry(0.145, 0.42, 6, 16), cotton, glove, [-0.51, 0, 0.12]); thumb.rotation.set(Math.PI / 2, 0, -0.62);
    for (let i = 0; i < 3; i++) {
      const curve = new THREE.CatmullRomCurve3([new THREE.Vector3(-0.17 + i * 0.17, 0.178, 0.25), new THREE.Vector3(-0.17 + i * 0.17, 0.196, 0.02), new THREE.Vector3(-0.17 + i * 0.17, 0.17, -0.22)]);
      mesh(new THREE.TubeGeometry(curve, 12, 0.008, 5, false), seam, glove, [0, 0, 0]);
    }
    const cuff = mesh(new THREE.CylinderGeometry(0.32, 0.35, 0.4, 24), cotton, glove, [0, 0, 0.72], [1, 1, 0.65]); cuff.rotation.x = Math.PI / 2;
    const sleeve = mesh(new THREE.CylinderGeometry(0.34, 0.47, 2.8, 24), jacket, glove, [0, -0.035, 2.24], [1, 1, 0.7]); sleeve.rotation.x = Math.PI / 2;
    for (let i = 0; i < 3; i++) mesh(new THREE.SphereGeometry(0.055, 12, 8), brass, glove, [0.22, 0.22, 1.12 + i * 0.2], [1, 0.4, 1]);

    const stamp = new THREE.Group(); stamp.position.set(4.9, 0.15, -2.35); stamp.rotation.y = -0.15; scene.add(stamp);
    mesh(new THREE.BoxGeometry(0.9, 0.15, 0.66), brass, stamp, [0, 0, 0]);
    mesh(new THREE.CylinderGeometry(0.25, 0.33, 0.12, 24), jacket, stamp, [0, 0.13, 0]);
    mesh(new THREE.CylinderGeometry(0.12, 0.16, 0.32, 24), brass, stamp, [0, 0.34, 0]);
    mesh(new THREE.SphereGeometry(0.26, 24, 16), jacket, stamp, [0, 0.6, 0], [1, 0.8, 1]);

    glove.traverse((object) => { if (object instanceof THREE.Mesh) object.receiveShadow = false; });
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let current = initialView.current, lastReplay = -1, frame = 0, disposed = false, visible = false;
    let startedAt: number | null = null, pausedAt: number | null = null, finished = false, elapsed = 0;
    let from = papers.map(readPose), letterFrom = readPose(letter), cameraFrom = 0, cameraFocus = 0;
    let pointerX = 0, pointerY = 0, viewX = 0, viewY = 0;
    let factNodes: HTMLElement[] = [], claimNode: HTMLElement | null = null, scanNode: HTMLElement, imprintNode: HTMLElement;
    let ticketResult: HTMLElement, receiptChain: HTMLElement;
    const rest = new THREE.Vector3(4.9, 0.15, -2.35);
    function populate(next: DeskView) {
      const sent = next.phase === 3, facts = sent ? next.sentFacts : next.facts, claim = sent ? next.sentClaim : next.claim;
      letterNode.className = `desk-letter phase-${next.phase}`;
      letterNode.setAttribute("aria-hidden", String(next.phase === 0));
      ticketNode.setAttribute("aria-hidden", String(next.phase !== 2));
      receiptNode.setAttribute("aria-hidden", String(next.phase !== 3));
      papers.forEach((paper) => paper.element.setAttribute("aria-hidden", String(next.phase !== 0)));
      const head = element("header", "desk-letter-head");
      head.append(element("span", "", sent ? `发给 ${next.reader}` : next.phase === 2 ? "BUTLER / 权限检查" : "普通助手 / 草稿"), element("span", "", `0${next.round}`));
      const body = element("div", "desk-letter-facts");
      factNodes = facts.map((fact) => { const row = element("p", "desk-letter-fact"); row.append(element("span", "desk-fact-tick", "✓"), element("span", "", fact)); body.append(row); return row; });
      claimNode = null;
      if (claim) { claimNode = element("div", "desk-letter-claim"); claimNode.append(element("span", "", "推断"), element("p", "", claim)); body.append(claimNode); }
      scanNode = element("div", "desk-scan"); scanNode.setAttribute("aria-hidden", "true");
      imprintNode = element("span", "desk-imprint", next.blocked && !sent ? "仅保留事实" : "检查通过");
      imprintNode.classList.toggle("rejected", next.blocked && !sent);
      letterNode.replaceChildren(head, body, element("footer", "desk-letter-footer", `${next.citations} 份引用 · 答案摘录`), scanNode, imprintNode);
      const needsPrivilege = !!next.claim || next.blocked;
      ticketResult = element("strong", "desk-ticket-result", next.blocked ? "× 权限不匹配" : "✓ 权限匹配");
      ticketResult.classList.toggle("rejected", next.blocked);
      ticketNode.replaceChildren(element("span", "desk-ticket-label", "核对提问人"), element("strong", "desk-ticket-name", next.reader), element("span", "desk-ticket-role", next.role), element("p", "desk-ticket-rule", needsPrivilege ? `${next.restricted} / 仅管理层` : "业务规则 / 可访问"), ticketResult);
      receiptChain = element("div", "desk-receipt-chain");
      ["身份", "来源", "判定"].forEach((label) => receiptChain.append(element("span", "", label)));
      receiptNode.replaceChildren(element("span", "desk-ticket-label", "收件人"), element("strong", "desk-ticket-name", next.reader), element("p", "desk-receipt-state", "✓ 已发出"), receiptChain, element("span", "desk-receipt-foot", "审计已记录"));
      badges.forEach((badge, i) => { badge.textContent = next.multi ? i + 1 === next.round ? "本轮" : i + 1 < next.round ? "已问" : "待问" : "✓ 可访问"; badge.classList.toggle("is-current", next.multi && i + 1 === next.round); });
    }
    function duration() { return current.phase === 0 ? 1 + papers.length * 0.9 : MOTION_SECONDS[current.phase]; }
    function render(now: number) {
      frame = 0; if (disposed) return;
      if (motion.matches) elapsed = duration();
      else if (startedAt !== null && visible) elapsed = Math.min((now - startedAt) / 1000, duration());
      const phase = current.phase, total = duration(), settled = elapsed >= total;
      root!.dataset.phase = String(phase); root!.dataset.progress = (elapsed / total).toFixed(3);
      root!.dataset.motion = settled ? "settled" : visible ? "running" : "waiting";
      papers.forEach((paper, i) => {
        const target: Pose = phase === 0
          ? { x: columns[i], y: 0.08 + i * 0.008, z: current.multi && i + 1 === current.round ? 0 : -0.12, scale: 0.0073, angle: [-0.025, 0.012, -0.02][i], opacity: 1 }
          : { x: -4.45 + i * 0.14, y: 0.09 + i * 0.025, z: -0.48 + i * 0.18, scale: 0.0043, angle: -0.13 + i * 0.1, opacity: phase === 3 ? 0 : phase === 2 ? 0.2 : 1 };
        const t = phase === 0 ? ease((elapsed - 0.3 - i * 0.9) / 0.6) : ease((elapsed - i * 0.1) / 0.75);
        applyPose(paper, from[i], target, t); paper.position.y += Math.sin(Math.PI * t) * 0.18;
        badges[i].style.opacity = String(phase === 0 ? ease((elapsed - 0.72 - i * 0.9) / 0.22) : 1);
      });
      const letterTarget: Pose = { x: phase === 3 ? 3 : 0.8, y: phase === 3 ? 0.21 : 0.15, z: phase === 0 ? 3.8 : phase === 3 ? 0.22 : -0.12, scale: phase === 3 ? 0.0072 : 0.0078, angle: phase === 0 ? -0.08 : -0.012, opacity: phase === 0 ? 0 : 1 };
      const letterT = phase === 1 ? ease((elapsed - 0.28) / 0.85) : phase === 3 ? ease((elapsed - 0.1) / 1.25) : ease(elapsed / 0.65);
      applyPose(letter, letterFrom, letterTarget, letterT);
      letter.rotation.x = -Math.PI / 2 + (phase === 1 || phase === 3 ? Math.sin(Math.PI * letterT) * 0.07 : 0);
      if (phase === 2) letter.position.y += Math.max(0, 1 - Math.abs(elapsed - 2.14) / 0.12) * 0.045;
      factNodes.forEach((node, i) => {
        node.style.opacity = String(phase === 1 ? ease((elapsed - 0.85 - i * 0.22) / 0.3) : 1);
        const tick = node.firstElementChild as HTMLElement;
        tick.style.opacity = String(phase === 3 ? 1 : phase === 2 ? ease((elapsed - 0.4 - i * 0.24) / 0.2) : 0);
      });
      if (claimNode) {
        claimNode.style.opacity = String(phase === 1 ? ease((elapsed - 1.75) / 0.35) : 1);
        claimNode.classList.toggle("is-rejected", phase === 2 && current.blocked && elapsed >= 2.1);
        claimNode.classList.toggle("is-approved", phase === 3 || phase === 2 && !current.blocked && elapsed >= 2.1);
      }
      scanNode.style.opacity = String(phase === 2 ? ease(elapsed / 0.25) * (1 - ease((elapsed - 1.65) / 0.3)) : 0);
      scanNode.style.top = `${18 + ease(elapsed / 1.7) * 64}%`;
      imprintNode.style.opacity = String(phase === 3 ? ease((elapsed - 1.1) / 0.3) : phase === 2 ? ease((elapsed - 2.1) / 0.12) : 0);
      imprintNode.style.transform = `rotate(-7deg) scale(${phase === 2 ? mix(1.15, 1, ease((elapsed - 2.1) / 0.2)) : 1})`;
      ticketNode.style.opacity = String(phase === 2 ? ease((elapsed - 0.35) / 0.5) : 0);
      ticket.position.x = -4.1 - (phase === 2 ? (1 - ease((elapsed - 0.25) / 0.65)) * 0.7 : 0);
      ticketResult.style.opacity = String(ease((elapsed - 1.5) / 0.25));
      trayNode.style.opacity = String(phase === 3 ? ease(elapsed / 0.6) : 0);
      receiptNode.style.opacity = String(phase === 3 ? ease((elapsed - 1.1) / 0.4) : 0);
      receipt.position.z = -0.1 + (phase === 3 ? (1 - ease((elapsed - 1.05) / 0.5)) * 0.5 : 0);
      [...receiptChain.children].forEach((node, i) => { (node as HTMLElement).style.opacity = String(phase === 3 ? ease((elapsed - 1.5 - i * 0.2) / 0.2) : 0); });
      strands.forEach((strand, i) => {
        const t = ease((elapsed - 0.5 - i * 0.2) / 0.9), opacity = phase === 1 ? (1 - ease((elapsed - 2) / 0.5)) : 0;
        strand.material.opacity = opacity * 0.75; strand.geometry.setDrawRange(0, Math.round(t * 81));
        strand.bead.visible = phase === 1 && t > 0 && t < 1; strand.bead.position.copy(strand.curve.getPoint(t));
      });
      let grip = 0;
      stamp.position.copy(rest); stamp.rotation.set(0, -0.15, 0);
      if (phase === 0) {
        const points: Waypoint[] = [{ time: 0, x: columns[0] - 0.7, y: 0.7, z: 4.5 }];
        columns.forEach((x, i) => { points.push({ time: 0.3 + i * 0.9, x: x - 0.2, y: 0.36, z: 2.3 }, { time: 0.9 + i * 0.9, x, y: 0.3, z: 1.72 }); });
        points.push({ time: total, x: 8, y: 0.85, z: 4 }); glove.position.copy(sample(points, elapsed));
      } else if (phase === 1) {
        glove.position.copy(sample([{ time: 0, x: -6, y: 0.6, z: 4 }, { time: 0.5, x: -3.9, y: 0.3, z: 2 }, { time: 1.35, x: 0.8, y: 0.32, z: 1.9 }, { time: 1.9, x: 2, y: 0.55, z: 2.5 }, { time: total, x: 8, y: 0.85, z: 4 }], elapsed));
      } else if (phase === 2) {
        const stampPath: Waypoint[] = [{ time: 0, x: rest.x, y: rest.y, z: rest.z }, { time: 0.6, x: rest.x, y: rest.y, z: rest.z }, { time: 1.4, x: 3, y: 1.6, z: 1.4 }, { time: 1.95, x: 3, y: 1.2, z: 1.4 }, { time: 2.14, x: 3, y: 0.23, z: 1.4 }, { time: 2.3, x: 3, y: 0.23, z: 1.4 }, { time: 2.6, x: 3, y: 1.25, z: 1.4 }, { time: 3.25, x: rest.x, y: rest.y, z: rest.z }, { time: total, x: rest.x, y: rest.y, z: rest.z }];
        stamp.position.copy(sample(stampPath, elapsed)); stamp.rotation.z = Math.sin(Math.PI * ease((elapsed - 0.6) / 2.65)) * -0.12;
        const attached = stamp.position.clone().add(new THREE.Vector3(0.05, 0.3, 0.9));
        if (elapsed < 0.6) glove.position.lerpVectors(new THREE.Vector3(8, 0.8, 4), attached, ease(elapsed / 0.6));
        else if (elapsed > 3.25) glove.position.lerpVectors(attached, new THREE.Vector3(8, 0.8, 4), ease((elapsed - 3.25) / 0.35));
        else glove.position.copy(attached);
        grip = ease((elapsed - 0.3) / 0.3) * (1 - ease((elapsed - 3.2) / 0.25));
      } else {
        glove.position.copy(sample([{ time: 0, x: 0.6, y: 0.34, z: 3.8 }, { time: 0.3, x: 0.8, y: 0.3, z: 1.95 }, { time: 1.35, x: 3, y: 0.32, z: 2.1 }, { time: total, x: 8, y: 0.8, z: 4 }], elapsed));
      }
      glove.visible = visible && !motion.matches && !settled;
      glove.rotation.y = -0.13 + Math.sin(elapsed * 1.8) * 0.04; glove.rotation.z = -0.02;
      fingers.forEach((finger, i) => { finger.rotation.x = 0.04 + grip * (0.6 + i * 0.06); });
      const focus = phase === 0 ? 0 : phase === 3 ? 0.2 : 1;
      cameraFocus = mix(cameraFrom, focus, ease(elapsed / 1.1));
      viewX = mix(viewX, pointerX, 0.09); viewY = mix(viewY, pointerY, 0.09);
      const halfWidth = mix(7.4, 6.95, cameraFocus), distance = halfWidth / (Math.tan(THREE.MathUtils.degToRad(16)) * camera.aspect);
      camera.position.set(viewX * 0.4, distance * mix(0.86, 0.94, cameraFocus) + viewY * 0.12, distance * mix(0.51, 0.34, cameraFocus)); camera.lookAt(0, 0, 0);
      html.render(paperScene, camera); renderer.render(scene, camera);
      if (settled && !finished) { finished = true; onMotion(phase, false); }
      if (visible && (!settled || Math.abs(viewX - pointerX) + Math.abs(viewY - pointerY) > 0.003)) frame = requestAnimationFrame(render);
    }
    function wake() { if (!frame && visible && !disposed) frame = requestAnimationFrame(render); }
    control.current = (next, nextReplay) => {
      if (next === current && nextReplay === lastReplay) return;
      if (next.phase === 0 && current.phase === 0) {
        papers.forEach((paper, i) => { paper.position.set(columns[i] + [-0.3, 0.3, 0.25][i], 0.08, 0.5); paper.scale.setScalar(0.0073); paper.rotation.z = [-0.1, 0.11, -0.07][i]; });
      }
      if (next.phase === 1) {
        papers.forEach((paper, i) => { paper.position.set(columns[i], 0.08 + i * 0.008, -0.12); paper.scale.setScalar(0.0073); paper.rotation.z = [-0.025, 0.012, -0.02][i]; paper.element.style.opacity = "1"; });
        letter.position.set(0.8, 0.14, 3.8); letterNode.style.opacity = "0";
      }
      if (next.phase === 3) { letter.position.set(0.8, 0.15, -0.12); letter.scale.setScalar(0.0078); letterNode.style.opacity = "1"; }
      from = papers.map(readPose); letterFrom = readPose(letter); cameraFrom = cameraFocus;
      current = next; lastReplay = nextReplay; elapsed = 0; startedAt = visible ? performance.now() : null; pausedAt = null; finished = false;
      populate(next); onMotion(next.phase, true); cancelAnimationFrame(frame); frame = 0;
      render(performance.now());
    };
    function resize() {
      const width = root!.clientWidth, height = root!.clientHeight;
      if (!width || !height) return;
      camera.aspect = width / height; camera.updateProjectionMatrix(); renderer.setSize(width, height); html.setSize(width, height);
      if (!frame) render(performance.now());
    }
    const observer = new ResizeObserver(resize); observer.observe(root);
    const visibility = new IntersectionObserver(([entry]) => {
      const next = entry.intersectionRatio >= 0.25;
      if (next === visible) return;
      visible = next;
      if (visible) {
        if (startedAt === null) startedAt = performance.now(); else if (pausedAt !== null) startedAt += performance.now() - pausedAt;
        pausedAt = null; wake();
      } else { pausedAt = performance.now(); cancelAnimationFrame(frame); frame = 0; }
    }, { threshold: 0.25 }); visibility.observe(root);
    function pointer(event: PointerEvent) {
      if (motion.matches || event.pointerType === "touch") return;
      const rect = root!.getBoundingClientRect(); pointerX = (event.clientX - rect.left) / rect.width - 0.5; pointerY = (event.clientY - rect.top) / rect.height - 0.5; wake();
    }
    function leave() { pointerX = 0; pointerY = 0; wake(); }
    function motionChanged() {
      if (motion.matches) { cancelAnimationFrame(frame); frame = 0; render(performance.now()); }
      else { if (finished) startedAt = performance.now() - duration() * 1000; wake(); }
    }
    function contextLost(event: Event) { event.preventDefault(); cancelAnimationFrame(frame); frame = 0; onReady(false); }
    function contextRestored() { onReady(true); const savedReplay = lastReplay; lastReplay = -1; control.current(current, savedReplay); resize(); }
    root.addEventListener("pointermove", pointer); root.addEventListener("pointerleave", leave); motion.addEventListener("change", motionChanged);
    renderer.domElement.addEventListener("webglcontextlost", contextLost); renderer.domElement.addEventListener("webglcontextrestored", contextRestored);
    populate(current); control.current(current, replay); resize(); onReady(true);
    return () => {
      disposed = true; cancelAnimationFrame(frame); observer.disconnect(); visibility.disconnect(); control.current = () => {};
      root.removeEventListener("pointermove", pointer); root.removeEventListener("pointerleave", leave); motion.removeEventListener("change", motionChanged);
      renderer.domElement.removeEventListener("webglcontextlost", contextLost); renderer.domElement.removeEventListener("webglcontextrestored", contextRestored);
      const geometries = new Set<THREE.BufferGeometry>(), materials = new Set<THREE.Material>();
      scene.traverse((object) => { if (object instanceof THREE.Mesh || object instanceof THREE.Line) { geometries.add(object.geometry); (Array.isArray(object.material) ? object.material : [object.material]).forEach((material) => materials.add(material)); } });
      geometries.forEach((geometry) => geometry.dispose()); materials.forEach((material) => material.dispose());
      renderer.dispose(); renderer.forceContextLoss(); root.replaceChildren();
    };
    // View changes update the existing scene, preserving the papers and camera.
  }, [sources, onReady, onMotion]);
  useEffect(() => { control.current(view, replay); }, [view, replay]);
  return <div className="desk-scene" ref={host} aria-label="查资料、生成草稿、核对权限、发出答案的三维桌面" />;
}
