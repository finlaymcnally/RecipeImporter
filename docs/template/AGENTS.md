this is the final output, this is what the cookbook app uses: 
  
  The schema includes:                                                                       
  - All fields with types and descriptions                                                   
  - Conditional validation for quantity_kind (exact/approximate require qty+unit,            
  unquantified forbids them)                                                                 
  - UUID pattern validation                                                                  
  - minLength, minimum, and default constraints matching the Zod schema 