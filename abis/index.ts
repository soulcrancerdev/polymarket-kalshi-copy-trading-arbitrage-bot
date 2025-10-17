export const abis = {
  factory: [
    "event PairCreated(address indexed token0, address indexed token1, address pair, uint)",
  ],
  router: [
    "function getAmountsOut(uint amountIn, address[] memory path) public view returns (uint[] memory amounts)",
    "function swapExactTokensForTokens(uint amountIn, uint amountOutMin, address[] calldata path, address to, uint deadline) external returns (uint[] memory amounts)",
  ],
  pair: ["event Mint(address indexed sender, uint amount0, uint amount1)"],
  WBNB: [
    "function approve(address sender, uint256 amount) public returns(bool)",
    "function balanceOf(address sender) public view returns(uint)",
  ],
};
