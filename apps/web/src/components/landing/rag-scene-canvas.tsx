"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useEffect, useState, type RefObject } from "react";
import * as THREE from "three";

import { RAG_PHASES, phaseAmount } from "./rag-scene-timeline";

const COLS = 4;
const ROWS = 6;
const COUNT = COLS * ROWS;
const NEAREST = 6;

const ION = new THREE.Color("#7B6CFF");
const RESOLVED = new THREE.Color("#4FD1A5");
const QUESTION_POS = new THREE.Vector3(1.3, 1.1, 0.6);
const ANSWER_POS = new THREE.Vector3(0, -1.75, 1.2);

function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function glowTexture(): THREE.Texture {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.25, "rgba(255,255,255,0.75)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
  }
  return new THREE.CanvasTexture(canvas);
}

/**
 * The whole scene as plain three.js objects. Kept outside React state so the
 * per-frame mutation stays out of render: React only mounts `root` once.
 */
class RagSceneModel {
  readonly root = new THREE.Group();

  private readonly doc: THREE.Vector3[] = [];
  private readonly split: THREE.Vector3[] = [];
  private readonly cloud: THREE.Vector3[] = [];
  private readonly gathered: THREE.Vector3[] = [];
  private readonly nearest: number[];

  private readonly docMat = new THREE.MeshBasicMaterial({ color: "#1F2229", transparent: true });
  private readonly chunkMat = new THREE.MeshBasicMaterial({ color: "#4B4290", transparent: true, side: THREE.DoubleSide });
  private readonly chunks: THREE.InstancedMesh;
  private readonly pointsGeo = new THREE.BufferGeometry();
  private readonly pointsMat: THREE.PointsMaterial;
  private readonly question: THREE.Mesh;
  private readonly questionMat = new THREE.MeshBasicMaterial({ color: "#EEECE7", transparent: true, opacity: 0 });
  private readonly linesGeo = new THREE.BufferGeometry();
  private readonly linesMat = new THREE.LineBasicMaterial({ color: "#EEECE7", transparent: true, opacity: 0 });
  private readonly answerMat = new THREE.MeshBasicMaterial({ color: "#1F2229", transparent: true, opacity: 0 });
  private readonly answerEdgeMat = new THREE.LineBasicMaterial({ color: "#4FD1A5", transparent: true, opacity: 0 });

  private readonly dummy = new THREE.Object3D();
  private readonly tmp = new THREE.Vector3();
  private readonly color = new THREE.Color();
  private smoothed = 0;

  constructor() {
    const rand = mulberry32(7);
    for (let i = 0; i < COUNT; i++) {
      const c = i % COLS;
      const r = Math.floor(i / COLS);
      const x = (c - (COLS - 1) / 2) * 0.56;
      const y = ((ROWS - 1) / 2 - r) * 0.44;
      this.doc.push(new THREE.Vector3(x, y, 0));
      this.split.push(new THREE.Vector3(x * 1.45, y * 1.4, (rand() - 0.5) * 0.8));
      const theta = rand() * Math.PI * 2;
      const phi = Math.acos(2 * rand() - 1);
      const radius = 1.2 + rand() * 1.3;
      this.cloud.push(
        new THREE.Vector3(
          radius * Math.sin(phi) * Math.cos(theta) * 1.3,
          radius * Math.cos(phi) * 0.9,
          radius * Math.sin(phi) * Math.sin(theta),
        ),
      );
    }
    this.nearest = this.cloud
      .map((p, i) => ({ i, d: p.distanceTo(QUESTION_POS) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, NEAREST)
      .map((o) => o.i);
    this.cloud.forEach((p, i) => {
      const slot = this.nearest.indexOf(i);
      this.gathered.push(
        slot === -1
          ? p.clone()
          : new THREE.Vector3(ANSWER_POS.x + (slot - (NEAREST - 1) / 2) * 0.32, ANSWER_POS.y + 0.18, ANSWER_POS.z + 0.02),
      );
    });

    const docCard = new THREE.Mesh(new THREE.PlaneGeometry(2.6, 3.2), this.docMat);
    docCard.position.z = -0.08;

    this.chunks = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), this.chunkMat, COUNT);

    this.pointsGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(COUNT * 3), 3));
    this.pointsGeo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(COUNT * 3), 3));
    this.pointsMat = new THREE.PointsMaterial({
      size: 0.32,
      map: glowTexture(),
      vertexColors: true,
      transparent: true,
      opacity: 0,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    this.question = new THREE.Mesh(new THREE.SphereGeometry(0.12, 24, 24), this.questionMat);
    this.question.position.copy(QUESTION_POS);
    this.question.scale.setScalar(0);

    this.linesGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(NEAREST * 6), 3));

    const answer = new THREE.Group();
    answer.position.copy(ANSWER_POS);
    const answerPlane = new THREE.PlaneGeometry(2.6, 0.8);
    answer.add(new THREE.Mesh(answerPlane, this.answerMat));
    answer.add(new THREE.LineSegments(new THREE.EdgesGeometry(answerPlane), this.answerEdgeMat));

    this.root.add(
      docCard,
      this.chunks,
      new THREE.Points(this.pointsGeo, this.pointsMat),
      this.question,
      new THREE.LineSegments(this.linesGeo, this.linesMat),
      answer,
    );
  }

  update(target: number, delta: number, time: number, pointer: THREE.Vector2) {
    this.smoothed = THREE.MathUtils.damp(this.smoothed, target, 6, delta);
    const p = this.smoothed;
    const split = phaseAmount(p, RAG_PHASES.split);
    const scatter = phaseAmount(p, RAG_PHASES.scatter);
    const glow = phaseAmount(p, RAG_PHASES.glow);
    const question = phaseAmount(p, RAG_PHASES.question);
    const gather = phaseAmount(p, RAG_PHASES.gather);
    const answer = phaseAmount(p, RAG_PHASES.answer);

    this.root.rotation.y = THREE.MathUtils.lerp(0, -0.5, scatter) * (1 - gather) + pointer.x * 0.08;
    this.root.rotation.x = pointer.y * -0.05;
    this.docMat.opacity = 1 - phaseAmount(p, RAG_PHASES.docFade);

    // Chunks: document grid, then split apart, then shrink into the cloud.
    const { dummy, tmp, color } = this;
    for (let i = 0; i < COUNT; i++) {
      tmp.copy(this.doc[i]).lerp(this.split[i], split).lerp(this.cloud[i], scatter);
      dummy.position.copy(tmp);
      dummy.rotation.set(0, 0, (split - scatter) * ((i % 3) - 1) * 0.12);
      const s = THREE.MathUtils.lerp(1, 0.18, scatter);
      dummy.scale.set(0.5 * s, 0.34 * s, 1);
      dummy.updateMatrix();
      this.chunks.setMatrixAt(i, dummy.matrix);
    }
    this.chunks.instanceMatrix.needsUpdate = true;
    this.chunkMat.opacity = 0.85 * (1 - glow);

    // Glowing points drift; the nearest ones pull into the answer card.
    const positions = this.pointsGeo.getAttribute("position") as THREE.BufferAttribute;
    const colors = this.pointsGeo.getAttribute("color") as THREE.BufferAttribute;
    for (let i = 0; i < COUNT; i++) {
      const near = this.nearest.includes(i);
      const drift = Math.sin(time * 0.6 + i) * 0.04 * (1 - gather);
      tmp.copy(this.cloud[i]).lerp(this.gathered[i], near ? gather : 0);
      positions.setXYZ(i, tmp.x, tmp.y + drift, tmp.z);
      color.copy(ION);
      if (near) color.lerp(RESOLVED, question);
      else color.multiplyScalar(1 - 0.75 * Math.max(question * 0.4, gather));
      colors.setXYZ(i, color.r, color.g, color.b);
    }
    positions.needsUpdate = true;
    colors.needsUpdate = true;
    this.pointsMat.opacity = glow;

    // Question marker and lines to its nearest neighbours.
    const pulse = 1 + Math.sin(time * 3) * 0.08;
    this.question.scale.setScalar(Math.max(0.0001, question * pulse * (1 - gather * 0.6)));
    this.questionMat.opacity = question * (1 - gather);
    const lines = this.linesGeo.getAttribute("position") as THREE.BufferAttribute;
    this.nearest.forEach((idx, k) => {
      lines.setXYZ(k * 2, QUESTION_POS.x, QUESTION_POS.y, QUESTION_POS.z);
      lines.setXYZ(k * 2 + 1, positions.getX(idx), positions.getY(idx), positions.getZ(idx));
    });
    lines.needsUpdate = true;
    this.linesMat.opacity = 0.5 * question * (1 - gather);

    this.answerMat.opacity = answer * 0.9;
    this.answerEdgeMat.opacity = answer;
  }

  dispose() {
    this.root.traverse((obj) => {
      if (obj instanceof THREE.Mesh || obj instanceof THREE.Points || obj instanceof THREE.LineSegments) {
        obj.geometry.dispose();
      }
    });
    this.pointsMat.map?.dispose();
    [this.docMat, this.chunkMat, this.pointsMat, this.questionMat, this.linesMat, this.answerMat, this.answerEdgeMat].forEach(
      (m) => m.dispose(),
    );
  }
}

function Scene({ progressRef }: { progressRef: RefObject<number> }) {
  const [model] = useState(() => new RagSceneModel());
  useEffect(() => () => model.dispose(), [model]);
  useFrame((state, delta) => {
    model.update(progressRef.current ?? 0, delta, state.clock.elapsedTime, state.pointer);
  });
  return <primitive object={model.root} />;
}

export default function RagSceneCanvas({
  progressRef,
  running,
}: {
  progressRef: RefObject<number>;
  running: boolean;
}) {
  return (
    <Canvas
      className="!absolute inset-0"
      camera={{ position: [0, 0, 6.2], fov: 45 }}
      dpr={[1, 1.5]}
      gl={{ antialias: true, alpha: true }}
      frameloop={running ? "always" : "never"}
    >
      <Scene progressRef={progressRef} />
    </Canvas>
  );
}
