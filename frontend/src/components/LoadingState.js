function LoadingState({ message = "Loading..." }) {
  return (
    <div className="state-card">
      <div className="spinner" />
      <p>{message}</p>
    </div>
  );
}

export default LoadingState;
