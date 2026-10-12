"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";

function FacetedCore() {
  const meshRef = useRef<THREE.Mesh>(null);
  const wireRef = useRef<THREE.LineSegments>(null);
  const targetRotation = useRef({ x: 0, y: 0 });

  useFrame((state, delta) => {
    if (!meshRef.current || !wireRef.current) return;

    // Base continuous rotation
    meshRef.current.rotation.y += delta * 0.4;
    meshRef.current.rotation.x += delta * 0.15;
    wireRef.current.rotation.y = meshRef.current.rotation.y;
    wireRef.current.rotation.x = meshRef.current.rotation.x;

    // Mouse tilt tracking
    const mouseX = state.pointer.x * 0.6;
    const mouseY = state.pointer.y * 0.6;

    targetRotation.current.x = THREE.MathUtils.lerp(targetRotation.current.x, mouseY, 0.08);
    targetRotation.current.y = THREE.MathUtils.lerp(targetRotation.current.y, mouseX, 0.08);

    meshRef.current.position.x = THREE.MathUtils.lerp(meshRef.current.position.x, mouseX * 0.4, 0.05);
    meshRef.current.position.y = THREE.MathUtils.lerp(meshRef.current.position.y, mouseY * 0.4, 0.05);
    wireRef.current.position.x = meshRef.current.position.x;
    wireRef.current.position.y = meshRef.current.position.y;
  });

  return (
    <group scale={1.85}>
      {/* Solid Faceted Mesh */}
      <mesh ref={meshRef}>
        <icosahedronGeometry args={[1, 0]} />
        <meshStandardMaterial
          color="#7B6CFF"
          roughness={0.25}
          metalness={0.7}
          flatShading={true}
        />
      </mesh>

      {/* Edge Wireframe Outline */}
      <lineSegments ref={wireRef}>
        <edgesGeometry args={[new THREE.IcosahedronGeometry(1.002, 0)]} />
        <lineBasicMaterial color="#EEECE7" opacity={0.4} transparent linewidth={1.5} />
      </lineSegments>
    </group>
  );
}

export default function CoreScene() {
  return (
    <div className="relative size-full min-h-[300px] sm:min-h-[400px]">
      <Canvas
        camera={{ position: [0, 0, 4.5], fov: 45 }}
        gl={{ antialias: true, alpha: true }}
        dpr={[1, 1.5]}
      >
        <ambientLight intensity={0.7} />
        <directionalLight position={[10, 10, 10]} intensity={1.8} color="#FFFFFF" />
        <directionalLight position={[-10, -10, -5]} intensity={1.2} color="#7B6CFF" />
        <pointLight position={[0, 0, 2]} intensity={0.8} color="#8F82FF" />
        <FacetedCore />
      </Canvas>
    </div>
  );
}

