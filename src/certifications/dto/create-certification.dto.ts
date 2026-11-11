import { IsArray, IsInt, IsOptional, IsString, IsUrl } from 'class-validator';

export class CreateCertificationDto {
  @IsString()
  name!: string;

  @IsString()
  issuer!: string;

  @IsOptional()
  @IsString()
  date?: string;

  @IsOptional()
  @IsString()
  status?: string;

  @IsOptional()
  @IsString()
  credential_id?: string;

  @IsOptional()
  @IsString()
  description?: string;

  @IsOptional()
  @IsArray()
  @IsString({ each: true })
  skills?: string[];

  @IsOptional()
  @IsUrl()
  url?: string;

  @IsOptional()
  @IsInt()
  sort_order?: number;
}
